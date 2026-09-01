from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction
from .models import ArtisanProfile, BuyerProfile

User = get_user_model()

class ArtisanProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArtisanProfile
        fields = ['id', 'craft_type', 'bio', 'verified']

class BuyerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuyerProfile
        fields = ['id']

class UserSerializer(serializers.ModelSerializer):
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'phone', 'role', 'region', 'preferred_language', 'profile']

    def get_profile(self, obj):
        if obj.role == 'artisan':
            try:
                return ArtisanProfileSerializer(obj.artisan_profile).data
            except ArtisanProfile.DoesNotExist:
                return None
        elif obj.role == 'buyer':
            try:
                return BuyerProfileSerializer(obj.buyer_profile).data
            except BuyerProfile.DoesNotExist:
                return None
        return None


class SignupSerializer(serializers.ModelSerializer):
    craft_type = serializers.CharField(required=False, allow_blank=True, default='')
    password = serializers.CharField(write_only=True, min_length=4)

    class Meta:
        model = User
        fields = ['username', 'password', 'phone', 'email', 'role', 'region', 'preferred_language', 'craft_type']
        extra_kwargs = {
            'email': {'required': True, 'allow_blank': False},
            'region': {'required': False, 'allow_blank': True},
            'preferred_language': {'required': False},
        }

    def validate_phone(self, value):
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value

    def validate_role(self, value):
        if value not in ['artisan', 'buyer']:
            raise serializers.ValidationError("Role must be either 'artisan' or 'buyer'.")
        return value

    def validate(self, attrs):
        from django.core.cache import cache
        phone = attrs.get('phone')
        if not phone:
            raise serializers.ValidationError({"phone": ["Phone number is required."]})
        
        # Verify the phone was validated by OTP beforehand
        is_verified = cache.get(f"phone_verified:{phone}")
        if not is_verified:
            raise serializers.ValidationError({"phone": ["Phone number verification required. Please verify via OTP first."]})
        return attrs

    def create(self, validated_data):
        from django.core.cache import cache
        craft_type = validated_data.pop('craft_type', '')
        password = validated_data.pop('password')
        phone = validated_data.get('phone')
        
        with transaction.atomic():
            user = User(**validated_data)
            user.set_password(password)
            user.save()

            if user.role == 'artisan':
                ArtisanProfile.objects.create(user=user, craft_type=craft_type)
            elif user.role == 'buyer':
                BuyerProfile.objects.create(user=user)
                
            # Clear verification state on success
            cache.delete(f"phone_verified:{phone}")
                
        return user

