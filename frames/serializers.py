import os
import logging
from rest_framework import serializers
from django.conf import settings
from .models import Reel, ReelLike
from listings.models import Product

logger = logging.getLogger(__name__)


def resolve_media_url(field_file, default_type='image'):
    """
    Returns absolute Cloudinary HTTPS CDN URL for a FieldFile or local fallback URL.
    """
    if not field_file:
        return None

    try:
        raw_url = field_file.url
        if raw_url and raw_url.startswith(('http://', 'https://')):
            return raw_url
    except Exception:
        raw_url = ""

    cloud_name = getattr(settings, 'CLOUDINARY_CLOUD_NAME', '').strip() or 'q4xw3e2i'
    field_name = str(field_file.name or '').strip().replace('\\', '/')

    if cloud_name and field_name:
        clean_path = field_name.lstrip('/')
        # Cloudinary resource type prefix: video vs image
        resource_type = 'video' if default_type == 'video' or clean_path.endswith(('.mp4', '.mov', '.webm', '.avi', '.mkv')) else 'image'
        return f"https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{clean_path}"

    if field_name:
        base_url = getattr(settings, 'SITE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        clean_path = field_name if field_name.startswith('/') else f"/{field_name}"
        return f"{base_url}{clean_path}"

    return None


class ReelSerializer(serializers.ModelSerializer):
    artisan_id = serializers.IntegerField(source='artisan.id', read_only=True)
    artisan_name = serializers.SerializerMethodField()
    artisan_avatar = serializers.SerializerMethodField()
    artisan_region = serializers.SerializerMethodField()
    craft_type = serializers.SerializerMethodField()
    product_id = serializers.IntegerField(source='product.id', read_only=True, allow_null=True)
    product_title = serializers.SerializerMethodField()
    product_price = serializers.DecimalField(source='product.price', max_digits=10, decimal_places=2, read_only=True, allow_null=True)
    product_image = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    is_liked_by_me = serializers.SerializerMethodField()
    video_file = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Reel
        fields = [
            'id',
            'video_file',
            'thumbnail',
            'caption',
            'artisan_id',
            'artisan_name',
            'artisan_avatar',
            'artisan_region',
            'craft_type',
            'product_id',
            'product_title',
            'product_price',
            'product_image',
            'view_count',
            'like_count',
            'is_liked_by_me',
            'created_at',
        ]
        read_only_fields = ['id', 'view_count', 'created_at']

    def get_video_file(self, obj):
        return resolve_media_url(obj.video_file, default_type='video')

    def get_thumbnail(self, obj):
        return resolve_media_url(obj.thumbnail, default_type='image')

    def get_artisan_name(self, obj):
        if not obj.artisan or not obj.artisan.user:
            return "Master Artisan"
        u = obj.artisan.user
        full_name = f"{u.first_name} {u.last_name}".strip()
        if not full_name:
            full_name = (u.username or "").replace('_', ' ').replace('-', ' ').title()
        return full_name or "Master Artisan"

    def get_artisan_avatar(self, obj):
        if obj.artisan and obj.artisan.user:
            u = obj.artisan.user
            name = (u.first_name or u.username or "A").strip()
            return name[0].upper() if name else "A"
        return "A"

    def get_artisan_region(self, obj):
        if obj.artisan and obj.artisan.user:
            return getattr(obj.artisan.user, 'region', '') or ''
        return ''

    def get_craft_type(self, obj):
        if obj.artisan and obj.artisan.craft_type:
            return obj.artisan.craft_type.title()
        if obj.product and obj.product.category:
            return obj.product.category.name.title()
        return "Handmade Craft"

    def get_product_title(self, obj):
        if not obj.product:
            return None
        return obj.product.title_en or obj.product.title_hi or "Handcrafted Item"

    def get_product_image(self, obj):
        if not obj.product:
            return None
        img_field = obj.product.refined_image or obj.product.raw_image
        return resolve_media_url(img_field, default_type='image')

    def get_like_count(self, obj):
        if hasattr(obj, 'likes_count_annotated'):
            return obj.likes_count_annotated
        return obj.likes.count()

    def get_is_liked_by_me(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False

        # If preloaded via set or annotation in context
        liked_reel_ids = self.context.get('liked_reel_ids')
        if liked_reel_ids is not None:
            return obj.id in liked_reel_ids

        return obj.likes.filter(user=request.user).exists()


class ReelUploadSerializer(serializers.Serializer):
    video_file = serializers.FileField(required=True)
    thumbnail = serializers.ImageField(required=False, allow_null=True)
    caption = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')
    product_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_video_file(self, value):
        if not value:
            raise serializers.ValidationError("A video file is required.")
        # Maximum allowed video size: 100MB
        if value.size > 100 * 1024 * 1024:
            raise serializers.ValidationError("Video file size cannot exceed 100MB.")
        return value

    def validate_product_id(self, value):
        if value:
            request = self.context.get('request')
            try:
                product = Product.objects.get(id=value)
                if request and hasattr(request.user, 'artisan_profile'):
                    if product.artisan_id != request.user.artisan_profile.id:
                        raise serializers.ValidationError("You can only link a Frame to your own product.")
                return product
            except Product.DoesNotExist:
                raise serializers.ValidationError("The selected product does not exist.")
        return None

