from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from accounts.models import User, ArtisanProfile, BuyerProfile
from listings.models import Product
from cart.models import CartItem, Order, Address
from decimal import Decimal
import threading

class CheckoutSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='buyer1', phone='919999999991', role='buyer')
        self.buyer = BuyerProfile.objects.create(user=self.user)
        self.artisan_user = User.objects.create_user(username='artisan1', phone='919999999992', role='artisan')
        self.artisan = ArtisanProfile.objects.create(user=self.artisan_user)
        
        self.address = Address.objects.create(
            user=self.user,
            full_name='Test Buyer',
            phone='919999999991',
            line1='123 Test St',
            city='Test City',
            state='TS',
            postal_code='123456',
            country='India'
        )
        
        self.product = Product.objects.create(
            artisan=self.artisan,
            title_en='Test Product',
            price=100.00,
            status='live',
            raw_image='test.jpg'
        )
        
        self.cart_item = CartItem.objects.create(
            buyer=self.buyer,
            product=self.product,
            quantity=1
        )
        
        self.client.force_authenticate(user=self.user)
        self.url = '/api/orders/create/'

    @patch('cart.views.create_razorpay_order')
    def test_concurrent_checkout_state_change(self, mock_create):
        """NEW-P3: If the order status changes during Razorpay API call, it aborts."""
        # 1. We mock razorpay order creation
        mock_create.return_value = {'id': 'order_rzp12345'}
        
        # 2. We override the create_razorpay_order to ALSO change the order status (simulating a race)
        def side_effect(*args, **kwargs):
            # Change the order status to cancelled
            Order.objects.filter(buyer=self.buyer).update(status='cancelled')
            return {'id': 'order_rzp12345'}
            
        mock_create.side_effect = side_effect
        
        # 3. Call the checkout endpoint
        response = self.client.post(self.url, {'address_id': self.address.id}, format='json')
        
        # 4. It should detect the state change and return 409
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        
        # 5. Order should still be cancelled and NOT have the razorpay ID
        order = Order.objects.get(buyer=self.buyer)
        self.assertEqual(order.status, 'cancelled')
        self.assertIsNone(order.razorpay_order_id)
