from rest_framework import serializers
from .models import CartItem, Order, Address
from listings.models import Product


class ProductMiniSerializer(serializers.ModelSerializer):
    refined_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'title_en', 'price', 'refined_image']

    def get_refined_image(self, obj):
        request = self.context.get('request')
        if obj.refined_image:
            url = obj.refined_image.url
            return request.build_absolute_uri(url) if request else url
        return None


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductMiniSerializer(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), source='product', write_only=True
    )
    subtotal = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ['id', 'product', 'product_id', 'quantity', 'added_at', 'subtotal']
        read_only_fields = ['id', 'added_at']

    def get_subtotal(self, obj):
        return float(obj.product.price) * obj.quantity


class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = ['id', 'label', 'full_name', 'phone', 'line1', 'line2', 'city', 'state', 'postal_code', 'country']


class OrderSerializer(serializers.ModelSerializer):
    product = ProductMiniSerializer(read_only=True)
    shipping_address = AddressSerializer(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'product', 'quantity', 'total_amount', 'currency', 'status',
            'product_total', 'shipping_cost', 'platform_commission', 'total_payable',
            'shipping_address', 'created_at',
        ]
        read_only_fields = fields
