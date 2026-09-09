from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
from accounts.models import BuyerProfile, ArtisanProfile
from listings.models import Product, Category
from cart.models import CartItem
from decimal import Decimal
import os

User = get_user_model()

class SIHSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='buyer1', phone='1234567890', password='pass')
        self.user.role = 'buyer'
        self.user.save()
        self.buyer_profile, _ = BuyerProfile.objects.get_or_create(user=self.user)

        self.artisan_user = User.objects.create_user(username='artisan1', phone='0987654321', password='pass')
        self.artisan_user.role = 'artisan'
        self.artisan_user.save()
        self.artisan_profile, _ = ArtisanProfile.objects.get_or_create(user=self.artisan_user)
        
        self.category = Category.objects.create(name='Test Category')
        
        self.product = Product.objects.create(
            artisan=self.artisan_profile,
            category=self.category,
            title_en='Test Product',
            price=Decimal('100.00'),
            status='live'
        )

    def test_bug5_negative_product_price(self):
        from django.core.exceptions import ValidationError
        p = Product(artisan=self.artisan_profile, price=Decimal('-10.00'), status='live')
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_bug5_negative_price_upload(self):
        self.client.force_authenticate(user=self.artisan_user)
        with open('test_img.jpg', 'wb') as f:
            f.write(b'fakeimage')
        with open('test_img.jpg', 'rb') as f:
            res = self.client.post('/api/listings/upload/', {
                'title_en': 'Bad Price',
                'price': '-50',
                'raw_image': f
            }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('price', res.data)
        os.remove('test_img.jpg')

    def test_bug6_non_live_products_checkout(self):
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        self.product.status = 'flagged'
        self.product.save()

        self.client.force_authenticate(user=self.user)
        from cart.models import Address
        addr = Address.objects.create(user=self.user, full_name='Test', phone='123', line1='A', city='B', state='C', postal_code='123')
        res = self.client.post('/api/orders/create/', {'address_id': addr.id})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('no longer available', res.data['detail'])

    def test_bug2_otp_throttle_verify(self):
        from django.core.cache import cache
        cache.clear()
        # VerifyOTPView should block after 5 requests
        for i in range(5):
            res = self.client.post('/api/accounts/verify-otp/', {'phone': '1234567890', 'otp': '000000'}, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST) # Bad Request means it hit the view
        
        res = self.client.post('/api/accounts/verify-otp/', {'phone': '1234567890', 'otp': '000000'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_bug2_otp_throttle_password(self):
        from django.core.cache import cache
        cache.clear()
        # PasswordResetConfirmView should block after 5 requests
        for i in range(5):
            res = self.client.post('/api/accounts/password-reset/confirm/', {'phone': '1234567890', 'otp': '000000', 'new_password': '123'}, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        
        res = self.client.post('/api/accounts/password-reset/confirm/', {'phone': '1234567890', 'otp': '000000', 'new_password': '123'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_bug1_decompression_bomb_catch(self):
        from ai_services.refiner import refine_image
        import io
        from PIL import Image
        
        img = Image.new('RGB', (5000, 5000))
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        buf.seek(0)
        buf.name = "bomb.jpg"
        
        with self.assertRaises(ValueError) as context:
            refine_image(buf)
        
        self.assertTrue('exceed the safe limit' in str(context.exception))





    def test_bug7_audio_orphaning(self):
        client = APIClient()
        client.force_authenticate(user=self.artisan_user)
        from django.core.files.uploadedfile import SimpleUploadedFile
        audio_content = b"ID3" + b"\x00" * 100
        old_audio = SimpleUploadedFile("old.mp3", audio_content, content_type="audio/mpeg")
        self.product.raw_audio.save("old.mp3", old_audio)
        
        old_name = self.product.raw_audio.name
        
        new_audio = SimpleUploadedFile("new.mp3", audio_content, content_type="audio/mpeg")
        res = client.post(f'/api/listings/{self.product.id}/voice-catalog/', {'audio_file': new_audio}, format='multipart')
        
        self.product.refresh_from_db()
        self.assertNotEqual(self.product.raw_audio.name, old_name)
        self.assertFalse(self.product.raw_audio.storage.exists(old_name))

    def test_bug8_voice_upload_validation(self):
        client = APIClient()
        client.force_authenticate(user=self.artisan_user)
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        bad_ext = SimpleUploadedFile("malware.exe", b"ID3" + b"0"*10, content_type="audio/mpeg")
        res = client.post(f'/api/listings/{self.product.id}/voice-catalog/', {'audio_file': bad_ext}, format='multipart')
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported audio extension", res.data['detail'])
        
        bad_content = SimpleUploadedFile("renamed.mp3", b"MZ\x90\x00" + b"0"*10, content_type="audio/mpeg")
        res = client.post(f'/api/listings/{self.product.id}/voice-catalog/', {'audio_file': bad_content}, format='multipart')
        self.assertEqual(res.status_code, 400)
        self.assertIn("content does not match", res.data['detail'])

        oversized = SimpleUploadedFile("big.mp3", b"ID3" + b"0"*(5 * 1024 * 1024 + 10), content_type="audio/mpeg")
        res = client.post(f'/api/listings/{self.product.id}/voice-catalog/', {'audio_file': oversized}, format='multipart')
        self.assertEqual(res.status_code, 400)
        self.assertIn("too large", res.data['detail'])
        
        valid = SimpleUploadedFile("good.mp3", b"ID3" + b"0"*10, content_type="audio/mpeg")
        res = client.post(f'/api/listings/{self.product.id}/voice-catalog/', {'audio_file': valid}, format='multipart')
        self.assertNotEqual(res.status_code, 400)

    from unittest.mock import patch
    @patch('cart.views.create_razorpay_order')
    def test_bug9_razorpay_failure_rollback(self, mock_create_rzp):
        from cart.models import Address, Order
        mock_create_rzp.side_effect = Exception("Razorpay is down")
        
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        addr = Address.objects.create(user=self.user, full_name='Test', phone='123', line1='A', city='B', state='C', postal_code='123')
        
        self.client.force_authenticate(user=self.user)
        res = self.client.post('/api/orders/create/', {'address_id': addr.id})
        
        self.assertEqual(res.status_code, 502)
        orders = Order.objects.filter(buyer=self.buyer_profile)
        self.assertEqual(orders.count(), 1)
        self.assertTrue(all(o.status == 'cancelled' for o in orders))

    @patch('cart.views.create_razorpay_order')
    def test_bug10_duplicate_checkout_idempotency(self, mock_create_rzp):
        from cart.models import Address, Order
        mock_create_rzp.return_value = {'id': 'order_test123', 'amount': 10000}
        
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        addr = Address.objects.create(user=self.user, full_name='Test', phone='123', line1='A', city='B', state='C', postal_code='123')
        
        self.client.force_authenticate(user=self.user)
        
        res1 = self.client.post('/api/orders/create/', {'address_id': addr.id})
        self.assertEqual(res1.status_code, 201)
        
        res2 = self.client.post('/api/orders/create/', {'address_id': addr.id})
        self.assertEqual(res2.status_code, 201)
        self.assertEqual(res1.data['razorpay_order_id'], res2.data['razorpay_order_id'])
        
        orders = Order.objects.filter(buyer=self.buyer_profile, status='created')
        self.assertEqual(orders.count(), 1)

    @patch('cart.views.create_razorpay_order')
    def test_bug10_midflight_concurrency_simulation(self, mock_create_rzp):
        '''
        Simulates the effect of a concurrent checkout by manually placing a 'created'
        Order without a razorpay_order_id in the database before the second request arrives.
        This proves that if Thread 2 wakes up after Thread 1 creates the orders but 
        before Thread 1 finishes the Razorpay call, Thread 2 correctly returns a 409 Conflict.
        (Note: True multithreading causes SQLite OperationalError: database table is locked,
        but production MySQL/Aiven handles row-level select_for_update() properly).
        '''
        from cart.models import Address, Order
        mock_create_rzp.return_value = {'id': 'order_sync123', 'amount': 10000}
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        addr = Address.objects.create(user=self.user, full_name='Test', phone='123', line1='A', city='B', state='C', postal_code='123')
        
        # Simulate Thread 1's intermediate state (Order created, Razorpay call pending)
        Order.objects.create(
            buyer=self.buyer_profile,
            product=self.product,
            artisan=self.product.artisan,
            shipping_address=addr,
            quantity=1,
            total_amount=Decimal('100.00'),
            status='created',
            product_total=Decimal('100.00'),
            shipping_cost=Decimal('0.00'),
            platform_commission=Decimal('0.00'),
            total_payable=Decimal('100.00'),
            razorpay_order_id=None # MID-FLIGHT!
        )
        
        self.client.force_authenticate(user=self.user)
        # Thread 2 arrives
        res = self.client.post('/api/orders/create/', {'address_id': addr.id})
        print("res.status_code:", res.status_code)
        
        # Should be rejected with 409 Conflict
        self.assertEqual(res.status_code, 409)
        self.assertIn("in progress", res.data['detail'])

    def test_new3_cart_add_quantity_upper_bound(self):
        self.client.force_authenticate(user=self.user)
        # Attempt to add > 100 in single request
        res = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 101})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must not exceed 100', res.data['detail'])

        # Add valid quantity
        res = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 90})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        # Attempt to accumulate beyond 100
        res = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 20})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must not exceed 100', res.data['detail'])

    def test_new4_cart_quantity_non_integer_handled(self):
        self.client.force_authenticate(user=self.user)
        # Non-integer quantity in CartAddView
        res = self.client.post('/api/cart/add/', {'product_id': self.product.id, 'quantity': 'invalid_num'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must be a valid integer', res.data['detail'])

        # Add item to cart
        item = CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=5)

        # Non-integer in CartItemDetailView patch
        res = self.client.patch(f'/api/cart/{item.id}/', {'quantity': 'abc'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must be a valid integer', res.data['detail'])

        # Upper bound in patch
        res = self.client.patch(f'/api/cart/{item.id}/', {'quantity': 105})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must not exceed 100', res.data['detail'])

        # Zero in patch
        res = self.client.patch(f'/api/cart/{item.id}/', {'quantity': 0})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Valid patch
        res = self.client.patch(f'/api/cart/{item.id}/', {'quantity': 10})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['quantity'], 10)
