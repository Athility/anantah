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
