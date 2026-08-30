from rest_framework import serializers
from .models import Category, Product

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']


class ProductSerializer(serializers.ModelSerializer):
    raw_image_url = serializers.SerializerMethodField()
    refined_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'title_en', 'title_hi', 'description_en', 'description_hi', 
            'price', 'raw_image_url', 'refined_image_url', 'raw_audio', 
            'status', 'created_at'
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
