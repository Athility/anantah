import json
import logging
from django.conf import settings
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle

from cart.models import Order
from .razorpay_service import (
    create_razorpay_order,
    verify_payment_signature,
    verify_webhook_signature
)
from .verified_page_generator import generate_verified_page


logger = logging.getLogger(__name__)

class IsBuyer(IsAuthenticated):
    """
    Permission class checking that the user is authenticated and is a Buyer.
    """
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return hasattr(request.user, 'buyer_profile') and request.user.buyer_profile is not None


class CreateRazorpayOrderView(APIView):
    permission_classes = [IsBuyer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payments_create'

    def post(self, request):
        try:
            order_id = request.data.get('order_id')
            if not order_id:
                return Response({'detail': 'order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                buyer_profile = request.user.buyer_profile
                # IDOR protection: only fetch if order belongs to the logged-in buyer
                order = Order.objects.get(id=order_id, buyer=buyer_profile)
            except (Order.DoesNotExist, ValueError, TypeError):
                # Return 404 to avoid leaking existence of other users' orders
                return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)
            
            # Idempotency checks
            if order.status == 'paid':
                amount_paise = int(round(float(order.total_payable) * 100))
                return Response({
                    'detail': 'Order is already paid.',
                    'status': 'paid',
                    'our_order_id': order.id,
                    'razorpay_order_id': order.razorpay_order_id,
                    'amount': amount_paise,
                    'currency': 'INR',
                    'razorpay_key_id': settings.RAZORPAY_KEY_ID
                }, status=status.HTTP_200_OK)
            
            # Reuse existing Razorpay order if available and status is still 'created'
            if order.razorpay_order_id and order.status == 'created':
                amount_paise = int(round(float(order.total_payable) * 100))
                return Response({
                    'our_order_id': order.id,
                    'razorpay_order_id': order.razorpay_order_id,
                    'amount': amount_paise,
                    'currency': 'INR',
                    'razorpay_key_id': settings.RAZORPAY_KEY_ID
                }, status=status.HTTP_200_OK)
            
            # Call service to create new Razorpay order
            # Note: order.total_payable is used to prevent client-supplied amount manipulation
            rzp_order = create_razorpay_order(
                amount_rupees=order.total_payable,
                receipt_id=str(order.id)
            )
            
            # Save the Razorpay order ID to our DB
            order.razorpay_order_id = rzp_order['id']
            order.save()
            
            return Response({
                'our_order_id': order.id,
                'razorpay_order_id': rzp_order['id'],
                'amount': rzp_order['amount'],
                'currency': 'INR',
                'razorpay_key_id': settings.RAZORPAY_KEY_ID
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error creating Razorpay order: {str(e)}")
            return Response({'detail': f"Order creation failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


class VerifyPaymentView(APIView):
    permission_classes = [IsBuyer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'payments_verify'

    def post(self, request):
        try:
            razorpay_order_id = request.data.get('razorpay_order_id')
            razorpay_payment_id = request.data.get('razorpay_payment_id')
            razorpay_signature = request.data.get('razorpay_signature')
            
            if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
                return Response({'detail': 'Missing payment verification fields.'}, status=status.HTTP_400_BAD_REQUEST)
            
            buyer_profile = request.user.buyer_profile
            
            with transaction.atomic():
                orders = Order.objects.select_for_update().filter(razorpay_order_id=razorpay_order_id, buyer=buyer_profile)
                
                if not orders.exists():
                    return Response({'detail': 'Orders not found.'}, status=status.HTTP_404_NOT_FOUND)
                
                if all(o.status == 'paid' for o in orders):
                    return Response({'status': 'paid', 'detail': 'Orders are already marked as paid.'}, status=status.HTTP_200_OK)
                
                is_valid = verify_payment_signature(
                    razorpay_order_id=razorpay_order_id,
                    razorpay_payment_id=razorpay_payment_id,
                    razorpay_signature=razorpay_signature
                )
                
                if not is_valid:
                    orders.update(status='payment_failed')
                    return Response({'detail': 'Payment signature verification failed.', 'status': 'payment_failed'}, status=status.HTTP_400_BAD_REQUEST)
                
                orders.update(status='paid', razorpay_payment_id=razorpay_payment_id)
                
                # Auto-generate verified authenticity certificate pages for purchased products
                for o in orders:
                    if o.product:
                        generate_verified_page(o.product)

                # Clear purchased items from the cart
                from cart.models import CartItem
                purchased_product_ids = [o.product_id for o in orders if o.product_id]
                CartItem.objects.filter(buyer=buyer_profile, product_id__in=purchased_product_ids).delete()
                
                return Response({'status': 'paid'}, status=status.HTTP_200_OK)
                
        except Exception as e:
            logger.error(f"Error in payment verification: {str(e)}")
            return Response({'detail': f"Verification failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            received_sig = request.headers.get('x-razorpay-signature') or request.META.get('HTTP_X_RAZORPAY_SIGNATURE')
            if not received_sig:
                logger.warning("Webhook rejection: Missing signature header.")
                return Response({'detail': 'Missing signature header.'}, status=status.HTTP_400_BAD_REQUEST)
            
            raw_body = request.body
            # Cryptographic signature verification
            is_valid = verify_webhook_signature(raw_body, received_sig)
            if not is_valid:
                logger.warning("Webhook rejection: Webhook signature verification failed.")
                return Response({'detail': 'Invalid webhook signature.'}, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                payload = json.loads(raw_body.decode('utf-8'))
            except Exception:
                return Response({'detail': 'Invalid JSON.'}, status=status.HTTP_400_BAD_REQUEST)
            
            event_type = payload.get('event')
            
            # Secure logging: Log metadata but NEVER log card details, payment details, or secrets
            logger.info(f"Verified Razorpay Webhook Event received: {event_type}")
            
            if event_type == "payment.captured":
                payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
                rzp_order_id = payment_entity.get('order_id')
                rzp_payment_id = payment_entity.get('id')
                
                if not rzp_order_id or not rzp_payment_id:
                    logger.warning("Webhook warning: Missing order_id or payment_id in payload.")
                    return Response({'detail': 'Incomplete payload.'}, status=status.HTTP_200_OK)
                
                # Lock rows to prevent race conditions (idempotency wrapper)
                with transaction.atomic():
                    orders = Order.objects.select_for_update().filter(razorpay_order_id=rzp_order_id)
                    
                    if not orders.exists():
                        logger.error(f"Webhook error: No orders with razorpay_order_id {rzp_order_id} found.")
                        return Response({'detail': 'Order not found.'}, status=status.HTTP_200_OK)
                    
                    if all(o.status == 'paid' for o in orders):
                        logger.info(f"Webhook info: Orders for {rzp_order_id} are already paid.")
                        return Response({'detail': 'Orders already processed.'}, status=status.HTTP_200_OK)
                    
                    orders.update(status='paid', razorpay_payment_id=rzp_payment_id)
                    logger.info(f"Webhook success: {orders.count()} order(s) marked as paid for {rzp_order_id}.")
                    
                    # Auto-generate verified authenticity certificate pages for purchased products
                    for o in orders:
                        if o.product:
                            generate_verified_page(o.product)

                    # Cart cleanup: remove purchased items from the buyer's cart
                    from cart.models import CartItem
                    first_order = orders.first()
                    buyer = first_order.buyer if first_order else None
                    if buyer:
                        purchased_product_ids = [o.product_id for o in orders if o.product_id]
                        if purchased_product_ids:
                            CartItem.objects.filter(buyer=buyer, product_id__in=purchased_product_ids).delete()
            
            return Response({'status': 'processed'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Webhook processing error: {str(e)}")
            # Always return 200 to prevent Razorpay from retrying aggressively
            return Response({'detail': f"Webhook handling error: {str(e)}"}, status=status.HTTP_200_OK)

