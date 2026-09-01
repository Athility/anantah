from django.test import TestCase
from django.core.cache import cache
from accounts.serializers import SignupSerializer

class SignupSerializerTest(TestCase):
    def setUp(self):
        cache.clear()
        
    def test_signup_requires_email(self):
        # Seed cache for OTP verification
        phone = "1234567890"
        cache.set(f"phone_verified:{phone}", True)
        
        # Missing email
        data = {
            "username": "test_artisan",
            "phone": phone,
            "password": "securepassword",
            "role": "artisan",
            "craft_type": "Painting"
        }
        serializer = SignupSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)
        
        # Blank email
        data['email'] = ""
        serializer = SignupSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('email', serializer.errors)

        # Valid email
        data['email'] = "artisan@example.com"
        serializer = SignupSerializer(data=data)
        self.assertTrue(serializer.is_valid())

