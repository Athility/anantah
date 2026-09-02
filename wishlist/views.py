from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import WishlistItem
from .serializers import WishlistItemSerializer
from listings.models import Product


class IsBuyer(IsAuthenticated):
    """Allow only authenticated users with role='buyer'."""
    def has_permission(self, request, view):
        is_auth = super().has_permission(request, view)
        if not is_auth:
            return False
        return getattr(request.user, 'role', None) == 'buyer'


class WishlistAddView(APIView):
    """POST /api/wishlist/add/ — Add product to buyer's wishlist."""
    permission_classes = [IsBuyer]

    def post(self, request):
        product_id = request.data.get('product_id')
        if not product_id:
            return Response({'detail': 'product_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            product = Product.objects.get(id=product_id)
        except (Product.DoesNotExist, ValueError, TypeError):
            return Response({'detail': 'Product not found.'}, status=status.HTTP_404_NOT_FOUND)

        buyer_profile = getattr(request.user, 'buyer_profile', None)
        if not buyer_profile:
            return Response({'detail': 'Buyer profile not found.'}, status=status.HTTP_403_FORBIDDEN)

        item, created = WishlistItem.objects.get_or_create(
            buyer=buyer_profile,
            product=product
        )

        serializer = WishlistItemSerializer(item, context={'request': request})
        if created:
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response({
                'detail': 'Already in wishlist.',
                'wishlist_item': serializer.data
            }, status=status.HTTP_200_OK)


class WishlistListView(APIView):
    """GET /api/wishlist/ — List all wishlist items for the logged-in buyer."""
    permission_classes = [IsBuyer]

    def get(self, request):
        buyer_profile = getattr(request.user, 'buyer_profile', None)
        if not buyer_profile:
            return Response({'detail': 'Buyer profile not found.'}, status=status.HTTP_403_FORBIDDEN)

        items = WishlistItem.objects.filter(buyer=buyer_profile).select_related(
            'product', 'product__artisan', 'product__artisan__user'
        ).order_by('-added_at')
        
        serializer = WishlistItemSerializer(items, many=True, context={'request': request})
        return Response(serializer.data)


class WishlistItemDeleteView(APIView):
    """DELETE /api/wishlist/<item_id>/ — Remove an item from wishlist (buyer owned only)."""
    permission_classes = [IsBuyer]

    def delete(self, request, item_id):
        buyer_profile = getattr(request.user, 'buyer_profile', None)
        if not buyer_profile:
            return Response({'detail': 'Buyer profile not found.'}, status=status.HTTP_403_FORBIDDEN)

        try:
            item = WishlistItem.objects.get(id=item_id, buyer=buyer_profile)
        except WishlistItem.DoesNotExist:
            return Response({'detail': 'Wishlist item not found.'}, status=status.HTTP_404_NOT_FOUND)

        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WishlistCheckView(APIView):
    """GET /api/wishlist/check/<product_id>/ — Check if product is wishlisted by buyer."""
    permission_classes = [IsBuyer]

    def get(self, request, product_id):
        buyer_profile = getattr(request.user, 'buyer_profile', None)
        if not buyer_profile:
            return Response({'is_wishlisted': False, 'item_id': None})

        item = WishlistItem.objects.filter(buyer=buyer_profile, product_id=product_id).first()
        if item:
            return Response({'is_wishlisted': True, 'item_id': item.id})
        return Response({'is_wishlisted': False, 'item_id': None})
