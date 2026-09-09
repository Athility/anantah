"""
Cart + Order/Checkout views for Anantah.

Buyer-only access enforced via IsBuyer permission class.
All cost constants are clearly marked as placeholders for easy future swapping.
"""
from decimal import Decimal
from django.db import transaction
import uuid
from payments.razorpay_service import create_razorpay_order
from django.conf import settings

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import CartItem, Order, Address
from .serializers import CartItemSerializer, OrderSerializer, AddressSerializer
from listings.models import Product


# ─────────────────────────────────────────────────────────────────────────────
# Permission helper
# ─────────────────────────────────────────────────────────────────────────────

class IsBuyer(IsAuthenticated):
    """Allow only authenticated users with role='buyer'."""
    def has_permission(self, request, view):
        return (
            super().has_permission(request, view)
            and request.user.role == 'buyer'
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cost calculation — isolated here so swapping real rates is a 1-file change
# ─────────────────────────────────────────────────────────────────────────────

# PLACEHOLDER: Flat ₹80 shipping per order — replace with courier-rate API call
FLAT_SHIPPING_COST = Decimal('80.00')

# PLACEHOLDER: 5% platform commission — replace with configurable DB setting
PLATFORM_COMMISSION_RATE = Decimal('0.05')


def calculate_cart_costs(cart_items):
    """
    Given a queryset of CartItem objects, compute and return the full cost breakdown.
    Returns a dict: product_total, shipping_cost, platform_commission, total_payable.
    """
    product_total = sum(
        item.product.price * item.quantity for item in cart_items
    )
    shipping_cost = FLAT_SHIPPING_COST
    platform_commission = (product_total * PLATFORM_COMMISSION_RATE).quantize(Decimal('0.01'))
    total_payable = product_total + shipping_cost + platform_commission

    return {
        'product_total': product_total,
        'shipping_cost': shipping_cost,
        'platform_commission': platform_commission,
        'total_payable': total_payable,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cart endpoints
# ─────────────────────────────────────────────────────────────────────────────

class CartListView(APIView):
    """GET /api/cart/ — Returns all cart items + computed cart_total."""
    permission_classes = [IsBuyer]

    def get(self, request):
        items = CartItem.objects.filter(buyer=request.user.buyer_profile).select_related('product')
        serializer = CartItemSerializer(items, many=True, context={'request': request})
        cart_total = sum(
            item.product.price * item.quantity for item in items
        )
        return Response({
            'items': serializer.data,
            'cart_total': float(cart_total),
            'item_count': items.count(),
        })


class CartAddView(APIView):
    """POST /api/cart/add/ — Add product to cart or increment its quantity."""
    permission_classes = [IsBuyer]

    def post(self, request):
        product_id = request.data.get('product_id')
        try:
            quantity = int(request.data.get('quantity', 1))
        except (ValueError, TypeError):
            return Response({'detail': 'quantity must be a valid integer.'}, status=status.HTTP_400_BAD_REQUEST)

        if not product_id:
            return Response({'detail': 'product_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1:
            return Response({'detail': 'quantity must be at least 1.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity > 100:
            return Response({'detail': 'quantity must not exceed 100.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            product = Product.objects.get(id=product_id, status='live')
        except Product.DoesNotExist:
            return Response({'detail': 'Product not found or not live.'}, status=status.HTTP_404_NOT_FOUND)

        item, created = CartItem.objects.get_or_create(
            buyer=request.user.buyer_profile,
            product=product,
            defaults={'quantity': quantity}
        )
        if not created:
            new_qty = item.quantity + quantity
            if new_qty > 100:
                return Response({'detail': 'Total quantity for this item must not exceed 100.'}, status=status.HTTP_400_BAD_REQUEST)
            item.quantity = new_qty
            item.save()

        serializer = CartItemSerializer(item, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CartItemDetailView(APIView):
    """PATCH /api/cart/<item_id>/ and DELETE /api/cart/<item_id>/"""
    permission_classes = [IsBuyer]

    def _get_item(self, request, item_id):
        try:
            return CartItem.objects.get(id=item_id, buyer=request.user.buyer_profile)
        except CartItem.DoesNotExist:
            return None

    def patch(self, request, item_id):
        item = self._get_item(request, item_id)
        if not item:
            return Response({'detail': 'Cart item not found.'}, status=status.HTTP_404_NOT_FOUND)

        quantity = request.data.get('quantity')
        if quantity is None:
            return Response({'detail': 'quantity is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            quantity = int(quantity)
        except (ValueError, TypeError):
            return Response({'detail': 'quantity must be a valid integer.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1:
            return Response({'detail': 'quantity must be > 0.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity > 100:
            return Response({'detail': 'quantity must not exceed 100.'}, status=status.HTTP_400_BAD_REQUEST)

        item.quantity = quantity
        item.save()
        serializer = CartItemSerializer(item, context={'request': request})
        return Response(serializer.data)

    def delete(self, request, item_id):
        item = self._get_item(request, item_id)
        if not item:
            return Response({'detail': 'Cart item not found.'}, status=status.HTTP_404_NOT_FOUND)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# Address endpoint (for checkout screen)
# ─────────────────────────────────────────────────────────────────────────────

class AddressListCreateView(APIView):
    """GET and POST /api/cart/addresses/"""
    permission_classes = [IsBuyer]

    def get(self, request):
        addresses = Address.objects.filter(user=request.user)
        return Response(AddressSerializer(addresses, many=True).data)

    def post(self, request):
        serializer = AddressSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# Checkout endpoints
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutSummaryView(APIView):
    """
    POST /api/orders/checkout-summary/
    Reads the buyer's current cart, returns cost breakdown without creating an Order.
    """
    permission_classes = [IsBuyer]

    def post(self, request):
        items = CartItem.objects.filter(buyer=request.user.buyer_profile).select_related('product')
        if not items.exists():
            return Response({'detail': 'Your cart is empty.'}, status=status.HTTP_400_BAD_REQUEST)

        unavailable_items = [item.product.title_en for item in items if item.product.status != 'live']
        if unavailable_items:
            titles = ', '.join(unavailable_items)
            return Response(
                {'detail': f'The following items are no longer available: {titles}. Please remove them from your cart to proceed.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        costs = calculate_cart_costs(items)
        items_data = CartItemSerializer(items, many=True, context={'request': request}).data

        return Response({
            'items': items_data,
            **{k: float(v) for k, v in costs.items()},
        })


class OrderCreateView(APIView):
    """
    POST /api/orders/create/
    Creates Order rows from the buyer's cart, clears the cart, and returns the orders.

    NOTE: No payment is taken here. The 'Coming Soon' popup on the frontend
    informs the user that payment integration is pending. This endpoint is the
    single point to swap in Razorpay (or any gateway) in the future — just
    add payment verification BEFORE the Order rows are created below.
    """
    permission_classes = [IsBuyer]

    def post(self, request):
        address_id = request.data.get('address_id')
        if not address_id:
            return Response({'detail': 'address_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            address = Address.objects.get(id=address_id, user=request.user)
        except Address.DoesNotExist:
            return Response({'detail': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

        items = CartItem.objects.filter(buyer=request.user.buyer_profile).select_related('product', 'product__artisan')
        if not items.exists():
            return Response({'detail': 'Your cart is empty.'}, status=status.HTTP_400_BAD_REQUEST)

        unavailable_items = [item.product.title_en for item in items if item.product.status != 'live']
        if unavailable_items:
            titles = ', '.join(unavailable_items)
            return Response(
                {'detail': f'The following items are no longer available: {titles}. Please remove them from your cart to proceed.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        costs = calculate_cart_costs(items)
        items_list = list(items)  
        item_count = Decimal(len(items_list))
        
        # BUG-10: Idempotency / Duplicate Check & Concurrency protection
        # We need to lock cart items and check for mid-flight checkouts.
        created_orders = []
        with transaction.atomic():
            # Lock the cart to prevent concurrent Pay Now clicks from creating multiple orders.
            locked_items = list(CartItem.objects.filter(buyer=request.user.buyer_profile).select_for_update())
            
            existing_orders = list(Order.objects.filter(buyer=request.user.buyer_profile, status='created').select_for_update())
            
            # Check if existing orders perfectly match current cart + address
            cart_sig = {(item.product.id, item.quantity, item.product.price, int(address_id)) for item in locked_items}
            order_sig = {(o.product.id, o.quantity, o.product_total / o.quantity, o.shipping_address_id) for o in existing_orders}
            
            if existing_orders and cart_sig == order_sig:
                if any(not o.razorpay_order_id for o in existing_orders):
                    return Response({'detail': 'A checkout is already in progress. Please wait a moment.'}, status=status.HTTP_409_CONFLICT)
                
                # Match found with razorpay_order_id. Reuse it to prevent duplicates!
                serializer = OrderSerializer(existing_orders, many=True, context={'request': request})
                return Response({
                    'orders': serializer.data,
                    'summary': {k: float(v) for k, v in costs.items()},
                    'razorpay_order_id': existing_orders[0].razorpay_order_id,
                    'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', 'test_key'),
                    'amount': int(sum(o.total_payable for o in existing_orders) * 100),
                    'currency': 'INR',
                    'message': 'Orders retrieved successfully. Proceed to payment.',
                }, status=status.HTTP_201_CREATED)
            
            # Cancel mismatched existing orders
            if existing_orders:
                for o in existing_orders:
                    o.status = 'cancelled'
                    o.save(update_fields=['status'])

            for item in locked_items:
                product = item.product
                artisan_profile = product.artisan
                per_item_product_total = product.price * item.quantity
                per_item_shipping = (costs['shipping_cost'] / item_count).quantize(Decimal('0.01'))
                per_item_commission = (per_item_product_total * PLATFORM_COMMISSION_RATE).quantize(Decimal('0.01'))
                per_item_payable = per_item_product_total + per_item_shipping + per_item_commission

                order = Order.objects.create(
                    buyer=request.user.buyer_profile,
                    product=product,
                    artisan=artisan_profile,
                    shipping_address=address,
                    quantity=item.quantity,
                    total_amount=per_item_payable,
                    currency='INR',
                    status='created',
                    product_total=per_item_product_total,
                    shipping_cost=per_item_shipping,
                    platform_commission=per_item_commission,
                    total_payable=per_item_payable,
                )
                created_orders.append(order)

        # BUG-9: Step 2: Outside transaction, call Razorpay
        total_payable = sum(o.total_payable for o in created_orders)
        receipt_id = f"cart_{uuid.uuid4().hex[:15]}"
        try:
            rzp_order = create_razorpay_order(amount_rupees=float(total_payable), receipt_id=receipt_id)
        except Exception as e:
            # Step 3: Handle Razorpay failure gracefully by cancelling the pending orders
            with transaction.atomic():
                for o in created_orders:
                    o.status = 'cancelled'
                    o.save(update_fields=['status'])
            return Response({'detail': f'Payment gateway failed to initialize. Please try again.'}, status=status.HTTP_502_BAD_GATEWAY)

        # Step 4: Short follow-up transaction to attach Razorpay ID
        with transaction.atomic():
            # Lock the orders to ensure they haven't been cancelled concurrently
            order_ids = [o.id for o in created_orders]
            locked_orders = list(Order.objects.filter(id__in=order_ids).select_for_update())
            
            for order in locked_orders:
                if order.status != 'created':
                    # If any order was cancelled, we shouldn't attach the razorpay ID
                    # We should probably abort and return an error.
                    return Response({'detail': 'Order state changed during payment initialization.'}, status=status.HTTP_409_CONFLICT)
            
            for order in locked_orders:
                order.razorpay_order_id = rzp_order['id']
                order.save(update_fields=['razorpay_order_id'])
                
            # Update the created_orders list so the serializer has the latest data
            created_orders = locked_orders
                
        serializer = OrderSerializer(created_orders, many=True, context={'request': request})
        return Response({
            'orders': serializer.data,
            'summary': {k: float(v) for k, v in costs.items()},
            'razorpay_order_id': rzp_order['id'],
            'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', 'test_key'),
            'amount': rzp_order['amount'],
            'currency': 'INR',
            'message': 'Orders created successfully. Proceed to payment.',
        }, status=status.HTTP_201_CREATED)


class OrderListView(APIView):
    """GET /api/orders/ — list all orders for the buyer."""
    permission_classes = [IsBuyer]

    def get(self, request):
        orders = Order.objects.filter(buyer=request.user.buyer_profile).select_related('product', 'shipping_address').order_by('-created_at')
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)




