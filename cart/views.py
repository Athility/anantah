"""
Cart + Order/Checkout views for Anantah.

Buyer-only access enforced via IsBuyer permission class.
All cost constants are clearly marked as placeholders for easy future swapping.
"""
from decimal import Decimal

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
        quantity = int(request.data.get('quantity', 1))

        if not product_id:
            return Response({'detail': 'product_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if quantity < 1:
            return Response({'detail': 'quantity must be at least 1.'}, status=status.HTTP_400_BAD_REQUEST)

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
            item.quantity += quantity
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

        quantity = int(quantity)
        if quantity < 1:
            return Response({'detail': 'quantity must be > 0.'}, status=status.HTTP_400_BAD_REQUEST)

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

        costs = calculate_cart_costs(items)
        items_list = list(items)  # materialize so delete() below doesn't affect the loop
        item_count = Decimal(len(items_list))
        created_orders = []

        for item in items_list:
            # Each cart item becomes one order row
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
                status='payment_received',
                product_total=per_item_product_total,
                shipping_cost=per_item_shipping,
                platform_commission=per_item_commission,
                total_payable=per_item_payable,
            )
            created_orders.append(order)

        # Clear the buyer's cart now that orders are created
        CartItem.objects.filter(buyer=request.user.buyer_profile).delete()

        serializer = OrderSerializer(created_orders, many=True, context={'request': request})
        return Response({
            'orders': serializer.data,
            'summary': {k: float(v) for k, v in costs.items()},
            'message': 'Orders placed successfully. Payment coming soon!',
        }, status=status.HTTP_201_CREATED)


class OrderListView(APIView):
    """GET /api/orders/ — list all orders for the buyer."""
    permission_classes = [IsBuyer]

    def get(self, request):
        orders = Order.objects.filter(buyer=request.user.buyer_profile).select_related('product', 'shipping_address').order_by('-created_at')
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)
