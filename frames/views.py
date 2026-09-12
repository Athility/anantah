import logging
from django.db.models import F, Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import CursorPagination, PageNumberPagination

from .models import Reel, ReelLike
from .serializers import ReelSerializer, ReelUploadSerializer
from accounts.models import ArtisanProfile

logger = logging.getLogger(__name__)


class FrameFeedPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50


class FrameUploadView(APIView):
    """
    POST /api/frames/upload/
    Artisan-only endpoint to upload a new Frame (video reel).
    Accepts video_file, optional thumbnail, caption, and optional product_id.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, *args, **kwargs):
        user = request.user
        if getattr(user, 'role', None) != 'artisan':
            return Response(
                {"error": "Only registered artisans are authorized to upload Frames."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            artisan_profile = user.artisan_profile
        except ArtisanProfile.DoesNotExist:
            return Response(
                {"error": "Artisan profile not found for this user account."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = ReelUploadSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        product = validated_data.get('product_id')  # validated returns Product instance or None

        reel = Reel.objects.create(
            artisan=artisan_profile,
            product=product,
            video_file=validated_data['video_file'],
            thumbnail=validated_data.get('thumbnail'),
            caption=validated_data.get('caption', '')
        )

        response_serializer = ReelSerializer(reel, context={'request': request})
        logger.info(f"Artisan #{artisan_profile.pk} uploaded Frame #{reel.pk}")
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class FrameFeedView(APIView):
    """
    GET /api/frames/feed/
    Public/Buyer feed returning newest Frames with pagination.
    Includes is_liked_by_me per item when request is authenticated.
    """
    permission_classes = [AllowAny]
    pagination_class = FrameFeedPagination

    def get(self, request, *args, **kwargs):
        queryset = Reel.objects.select_related(
            'artisan',
            'artisan__user',
            'product',
            'product__category'
        ).annotate(
            likes_count_annotated=Count('likes', distinct=True)
        ).order_by('-created_at')

        # Pre-compute liked reel IDs for authenticated users to avoid N+1 queries
        liked_reel_ids = set()
        if request.user and request.user.is_authenticated:
            liked_reel_ids = set(
                ReelLike.objects.filter(user=request.user).values_list('reel_id', flat=True)
            )

        paginator = self.pagination_class()
        paginated_queryset = paginator.paginate_queryset(queryset, request)
        serializer = ReelSerializer(
            paginated_queryset,
            many=True,
            context={'request': request, 'liked_reel_ids': liked_reel_ids}
        )
        return paginator.get_paginated_response(serializer.data)


class FrameViewCountView(APIView):
    """
    POST /api/frames/<reel_id>/view/
    Increments the view_count of the Frame by 1 atomically.
    Debounced client-side per session.
    """
    permission_classes = [AllowAny]

    def post(self, request, reel_id, *args, **kwargs):
        reel = get_object_or_404(Reel, id=reel_id)
        Reel.objects.filter(id=reel_id).update(view_count=F('view_count') + 1)
        reel.refresh_from_db(fields=['view_count'])
        return Response({
            "success": True,
            "reel_id": reel.id,
            "view_count": reel.view_count
        }, status=status.HTTP_200_OK)


class FrameLikeToggleView(APIView):
    """
    POST /api/frames/<reel_id>/like/
    Toggles a like on the specified Frame for the authenticated user (buyer or artisan).
    Returns the new like state and updated like count.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, reel_id, *args, **kwargs):
        reel = get_object_or_404(Reel, id=reel_id)
        like, created = ReelLike.objects.get_or_create(reel=reel, user=request.user)

        if not created:
            # Already liked -> Unlike
            like.delete()
            is_liked = False
        else:
            is_liked = True

        like_count = reel.likes.count()
        return Response({
            "success": True,
            "reel_id": reel.id,
            "is_liked": is_liked,
            "like_count": like_count
        }, status=status.HTTP_200_OK)


class FrameMineView(APIView):
    """
    GET /api/frames/mine/
    Artisan-only endpoint returning the logged-in artisan's own uploaded Frames
    with their view_count and like_count for management.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        if getattr(user, 'role', None) != 'artisan':
            return Response(
                {"error": "Only artisans can access their uploaded Frames."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            artisan_profile = user.artisan_profile
        except ArtisanProfile.DoesNotExist:
            return Response(
                {"error": "Artisan profile not found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        queryset = Reel.objects.filter(artisan=artisan_profile).select_related(
            'product',
            'product__category'
        ).annotate(
            likes_count_annotated=Count('likes', distinct=True)
        ).order_by('-created_at')

        serializer = ReelSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class FrameStatsView(APIView):
    """
    GET /api/frames/<reel_id>/stats/
    Artisan-only endpoint returning detailed stats for a single Frame owned by the artisan.
    Returns 403 Forbidden if accessed by another user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, reel_id, *args, **kwargs):
        user = request.user
        if getattr(user, 'role', None) != 'artisan':
            return Response(
                {"error": "Only artisans can view Frame analytics."},
                status=status.HTTP_403_FORBIDDEN
            )

        reel = get_object_or_404(
            Reel.objects.select_related('artisan', 'artisan__user', 'product', 'product__category'),
            id=reel_id
        )

        # Ensure artisan ownership security check
        if not reel.artisan or reel.artisan.user_id != user.id:
            return Response(
                {"error": "You do not have permission to view stats for this Frame."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ReelSerializer(reel, context={'request': request})
        return Response({
            "success": True,
            "reel": serializer.data,
            "total_views": reel.view_count,
            "total_likes": reel.likes.count(),
        }, status=status.HTTP_200_OK)
