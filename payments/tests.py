import json
from unittest.mock import patch
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework import status

from cart.models import Order, Address
from listings.models import Product, Category
from accounts.models import BuyerProfile, ArtisanProfile

User = get_user_model()

class PaymentsTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        
        # Create users
        self.buyer1_user = User.objects.create_user(
            username='buyer1',
            password='password123',
            phone='9988776655',
            role='buyer'
        )
        self.buyer1_profile = BuyerProfile.objects.create(user=self.buyer1_user)
        
        self.buyer2_user = User.objects.create_user(
            username='buyer2',
            password='password123',
            phone='9988776656',
            role='buyer'
        )
        self.buyer2_profile = BuyerProfile.objects.create(user=self.buyer2_user)
        
        self.artisan_user = User.objects.create_user(
            username='artisan1',
            password='password123',
            phone='9988776657',
            role='artisan'
        )
        self.artisan_profile = ArtisanProfile.objects.create(user=self.artisan_user, craft_type='Pottery')
        
        # Create Category and Product
        self.category = Category.objects.create(name='Clay Crafts')
        self.product = Product.objects.create(
            artisan=self.artisan_profile,
            category=self.category,
            title_en='Terracotta Pot',
            price=150.00,
            status='live'
        )
        
        # Create Address
        self.address = Address.objects.create(
            user=self.buyer1_user,
            label='Home',
            full_name='Buyer One',
            phone='9988776655',
            line1='123 Main St',
            city='Delhi',
            state='Delhi',
            postal_code='110001'
        )
        
        # Create Order (initial status defaults to 'payment_received' but overridden to 'created' via custom save())
        self.order = Order.objects.create(
            buyer=self.buyer1_profile,
            product=self.product,
            artisan=self.artisan_profile,
            shipping_address=self.address,
            quantity=1,
            total_amount=237.50,
            total_payable=237.50,
            status='payment_received'
        )

    def test_create_order_unauthenticated(self):
        url = reverse('create-razorpay-order')
        response = self.client.post(url, {'order_id': self.order.id})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_order_as_artisan(self):
        self.client.force_authenticate(user=self.artisan_user)
        url = reverse('create-razorpay-order')
        response = self.client.post(url, {'order_id': self.order.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('payments.views.create_razorpay_order')
    def test_create_order_as_buyer_own(self, mock_create):
        mock_create.return_value = {
            'id': 'order_mock123',
            'amount': 23750,
            'currency': 'INR'
        }
        self.client.force_authenticate(user=self.buyer1_user)
        url = reverse('create-razorpay-order')
        response = self.client.post(url, {'order_id': self.order.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['razorpay_order_id'], 'order_mock123')
        
        # Check database
        self.order.refresh_from_db()
        self.assertEqual(self.order.razorpay_order_id, 'order_mock123')

    def test_create_order_as_buyer_different(self):
        self.client.force_authenticate(user=self.buyer2_user)
        url = reverse('create-razorpay-order')
        response = self.client.post(url, {'order_id': self.order.id})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('payments.views.create_razorpay_order')
    def test_create_order_idempotency_reuse(self, mock_create):
        # Set existing razorpay_order_id on order
        self.order.razorpay_order_id = 'order_existing123'
        self.order.status = 'created'
        self.order.save()
        
        self.client.force_authenticate(user=self.buyer1_user)
        url = reverse('create-razorpay-order')
        response = self.client.post(url, {'order_id': self.order.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['razorpay_order_id'], 'order_existing123')
        
        # Verify API was NOT called since we reused the existing order id
        mock_create.assert_not_called()

    @patch('payments.views.verify_payment_signature')
    def test_verify_payment_success(self, mock_verify):
        mock_verify.return_value = True
        self.order.razorpay_order_id = 'order_valid123'
        self.order.status = 'created'
        self.order.save()
        
        self.client.force_authenticate(user=self.buyer1_user)
        url = reverse('verify-payment')
        data = {
            'our_order_id': self.order.id,
            'razorpay_order_id': 'order_valid123',
            'razorpay_payment_id': 'pay_123',
            'razorpay_signature': 'sig_123'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'paid')
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(self.order.razorpay_payment_id, 'pay_123')

    @patch('payments.views.verify_payment_signature')
    def test_verify_payment_failure(self, mock_verify):
        mock_verify.return_value = False
        self.order.razorpay_order_id = 'order_valid123'
        self.order.status = 'created'
        self.order.save()
        
        self.client.force_authenticate(user=self.buyer1_user)
        url = reverse('verify-payment')
        data = {
            'our_order_id': self.order.id,
            'razorpay_order_id': 'order_valid123',
            'razorpay_payment_id': 'pay_123',
            'razorpay_signature': 'sig_123'
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'payment_failed')

    @patch('payments.views.verify_webhook_signature')
    def test_webhook_payment_captured(self, mock_verify_webhook):
        mock_verify_webhook.return_value = True
        self.order.razorpay_order_id = 'order_web123'
        self.order.status = 'created'
        self.order.save()
        
        url = reverse('razorpay-webhook')
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_web999',
                        'order_id': 'order_web123'
                    }
                }
            }
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='dummy_sig'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(self.order.razorpay_payment_id, 'pay_web999')

    @patch('payments.views.verify_webhook_signature')
    def test_webhook_multi_item_payment_captured_and_cart_cleanup(self, mock_verify_webhook):
        from cart.models import CartItem
        mock_verify_webhook.return_value = True
        
        # Create second product and order sharing the same razorpay_order_id
        product2 = Product.objects.create(
            artisan=self.artisan_profile,
            category=self.category,
            title_en='Brass Bell',
            price=200.00,
            status='live'
        )
        
        self.order.razorpay_order_id = 'order_multi123'
        self.order.status = 'created'
        self.order.save()
        
        order2 = Order.objects.create(
            buyer=self.buyer1_profile,
            product=product2,
            artisan=self.artisan_profile,
            shipping_address=self.address,
            quantity=1,
            total_amount=280.00,
            total_payable=280.00,
            status='created',
            razorpay_order_id='order_multi123'
        )
        
        # Add items to buyer's cart
        CartItem.objects.create(buyer=self.buyer1_profile, product=self.product, quantity=1)
        CartItem.objects.create(buyer=self.buyer1_profile, product=product2, quantity=1)
        self.assertEqual(CartItem.objects.filter(buyer=self.buyer1_profile).count(), 2)
        
        url = reverse('razorpay-webhook')
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_multi_captured',
                        'order_id': 'order_multi123'
                    }
                }
            }
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='dummy_sig'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify BOTH orders are marked as paid
        self.order.refresh_from_db()
        order2.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(order2.status, 'paid')
        self.assertEqual(self.order.razorpay_payment_id, 'pay_multi_captured')
        self.assertEqual(order2.razorpay_payment_id, 'pay_multi_captured')
        
        # Verify cart was cleared for the purchased items
        self.assertEqual(CartItem.objects.filter(buyer=self.buyer1_profile).count(), 0)

    @patch('payments.views.verify_webhook_signature')
    def test_webhook_duplicate_delivery(self, mock_verify_webhook):
        mock_verify_webhook.return_value = True
        self.order.razorpay_order_id = 'order_dup123'
        self.order.status = 'created'
        self.order.save()
        
        url = reverse('razorpay-webhook')
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_dup123',
                        'order_id': 'order_dup123'
                    }
                }
            }
        }
        
        # First delivery
        res1 = self.client.post(url, data=json.dumps(payload), content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE='dummy_sig')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        
        # Second delivery (duplicate)
        res2 = self.client.post(url, data=json.dumps(payload), content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE='dummy_sig')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'paid')
        self.assertEqual(res2.data['detail'], 'Orders already processed.')

    @patch('payments.views.verify_webhook_signature')
    @patch('payments.views.verify_payment_signature')
    def test_webhook_and_frontend_verify_idempotency(self, mock_verify_sig, mock_verify_webhook):
        mock_verify_sig.return_value = True
        mock_verify_webhook.return_value = True
        
        self.order.razorpay_order_id = 'order_race123'
        self.order.status = 'created'
        self.order.save()
        
        # 1. Frontend verification arrives first
        self.client.force_authenticate(user=self.buyer1_user)
        verify_url = reverse('verify-payment')
        v_res = self.client.post(verify_url, {
            'razorpay_order_id': 'order_race123',
            'razorpay_payment_id': 'pay_race123',
            'razorpay_signature': 'sig_race123'
        })
        self.assertEqual(v_res.status_code, status.HTTP_200_OK)
        self.assertEqual(v_res.data['status'], 'paid')
        
        # 2. Webhook arrives second
        webhook_url = reverse('razorpay-webhook')
        payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': 'pay_race123',
                        'order_id': 'order_race123'
                    }
                }
            }
        }
        w_res = self.client.post(webhook_url, data=json.dumps(payload), content_type='application/json', HTTP_X_RAZORPAY_SIGNATURE='dummy_sig')
        self.assertEqual(w_res.status_code, status.HTTP_200_OK)
        self.assertEqual(w_res.data['detail'], 'Orders already processed.')

    def test_generate_verified_page_and_static_serving(self):
        import os
        from django.conf import settings
        from payments.verified_page_generator import generate_verified_page

        self.product.title_hi = 'मिट्टी का बर्तन'
        self.product.description_en = 'Authentic handcrafted clay pot by master artisan.'
        self.product.description_hi = 'पारंपरिक हस्तनिर्मित मिट्टी का पात्र।'
        self.product.save()

        # Remove any pre-existing file from previous tests
        existing_file = os.path.join(getattr(settings, 'VERIFIED_LINKS_DIR', settings.BASE_DIR / 'verified_links'), f"product_{self.product.id}.html")
        if os.path.exists(existing_file):
            try:
                os.remove(existing_file)
            except OSError:
                pass

        # 1. Generate verified page
        file_path = generate_verified_page(self.product)
        self.assertIsNotNone(file_path)
        self.assertTrue(os.path.exists(file_path))

        # 2. Verify file content structure
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertIn('Anantah', content)
        self.assertIn('VERIFIED AUTHENTIC', content)
        self.assertIn('Terracotta Pot', content)
        self.assertIn('मिट्टी का बर्तन', content)
        self.assertIn('Authentic handcrafted clay pot', content)
        self.assertIn('Artisan1', content)
        self.assertIn('Pottery', content)
        self.assertIn('Beauty of the art stays Eternal', content)
        self.assertIn(f"AN-AUTH-{self.product.id:06d}", content)
        self.assertIn(f"{settings.SITE_BASE_URL}/verified_links/product_{self.product.id}.html", content)

        # 3. Idempotency check: Repeated call should not crash and should return existing path
        second_path = generate_verified_page(self.product)
        self.assertEqual(file_path, second_path)

        # 4. HTTP Static Serving route check
        client_response = self.client.get(f"/verified_links/product_{self.product.id}.html")
        self.assertEqual(client_response.status_code, status.HTTP_200_OK)
        response_body = b''.join(client_response.streaming_content)
        self.assertIn(b'VERIFIED AUTHENTIC', response_body)

        # Clean up generated file after test
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass

    @patch('payments.views.verify_payment_signature')
    def test_verify_payment_triggers_verified_page_generation(self, mock_verify_sig):
        import os
        from django.conf import settings
        mock_verify_sig.return_value = True

        self.order.razorpay_order_id = 'order_vfd_123'
        self.order.status = 'created'
        self.order.save()

        expected_file = os.path.join(getattr(settings, 'VERIFIED_LINKS_DIR', settings.BASE_DIR / 'verified_links'), f"product_{self.product.id}.html")
        if os.path.exists(expected_file):
            try:
                os.remove(expected_file)
            except OSError:
                pass

        self.client.force_authenticate(user=self.buyer1_user)
        res = self.client.post(reverse('verify-payment'), {
            'razorpay_order_id': 'order_vfd_123',
            'razorpay_payment_id': 'pay_vfd_123',
            'razorpay_signature': 'sig_vfd_123'
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'paid')

        # Verify page was generated
        self.assertTrue(os.path.exists(expected_file))

        # Cleanup
        try:
            if os.path.exists(expected_file):
                os.remove(expected_file)
        except OSError:
            pass


