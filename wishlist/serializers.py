from rest_framework import serializers
from .models import WishlistItem
from listings.models import Product

class WishlistProductSerializer(serializers.ModelSerializer):
    raw_image_url = serializers.SerializerMethodField()
    refined_image_url = serializers.SerializerMethodField()
    raw_audio_url = serializers.SerializerMethodField()
    artisan_name = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'title_en', 'title_hi', 'description_en', 'description_hi',
            'price', 'raw_image_url', 'refined_image_url', 'raw_audio_url', 
            'artisan_name', 'category_name', 'status'
        ]

    def get_raw_image_url(self, obj):
        if obj.raw_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.raw_image.url)
            return obj.raw_image.url
        return None

    def get_refined_image_url(self, obj):
        if obj.refined_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.refined_image.url)
            return obj.refined_image.url
        return None

    def get_raw_audio_url(self, obj):
        if obj.raw_audio:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.raw_audio.url)
            return obj.raw_audio.url
        return None

    def get_artisan_name(self, obj):
        if obj.artisan and getattr(obj.artisan, 'user', None):
            user = obj.artisan.user
            full_name = f"{user.first_name} {user.last_name}".strip()
            return full_name if full_name else user.username
        return "Master Artisan"

    def get_category_name(self, obj):
        if obj.category:
            return obj.category.name
        return "Traditional Handicraft"


class WishlistItemSerializer(serializers.ModelSerializer):
    product = WishlistProductSerializer(read_only=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True)

    class Meta:
        model = WishlistItem
        fields = ['id', 'buyer_id', 'product_id', 'product', 'added_at']
