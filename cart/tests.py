from django.test import TestCase
from accounts.models import User
from listings.models import Product
from cart.models import CartItem, Order, Address
from rest_framework.test import APIClient
from rest_framework import status
from unittest import mock

class CheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer1', phone='1234567890', password='password', role='buyer')
        self.artisan_user = User.objects.create_user(username='art1', phone='0987654321', password='password', role='artisan')
        
        from accounts.models import BuyerProfile
        self.buyer_profile, _ = BuyerProfile.objects.get_or_create(user=self.user)
        from accounts.models import ArtisanProfile
        self.artisan_profile, _ = ArtisanProfile.objects.get_or_create(user=self.artisan_user)
        
        self.product = Product.objects.create(
            artisan=self.artisan_profile,
            title_en='Test Product',
            price=100.0,
            status='active'
        )
        
        self.address = Address.objects.create(
            user=self.user,
            label='Home',
            full_name='Test Buyer',
            phone='1234567890',
            line1='123 Test St',
            city='Test City',
            state='Test State',
            postal_code='12345',
            country='Test Country'
        )
        
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @mock.patch('cart.views.create_razorpay_order')
    def test_checkout_atomicity_rollback(self, mock_create):
        p2 = Product.objects.create(artisan=self.artisan_profile, title_en='Product 2', price=50.0, status='active')
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        CartItem.objects.create(buyer=self.buyer_profile, product=p2, quantity=1)
        
        mock_create.side_effect = Exception('Razorpay API down')
        
        response = self.client.post('/api/orders/create/', {'address_id': self.address.id}, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(CartItem.objects.filter(buyer=self.buyer_profile).count(), 2)

    def test_order_cascade_protection(self):
        order = Order.objects.create(
            buyer=self.buyer_profile,
            product=self.product,
            artisan=self.artisan_profile,
            shipping_address=self.address,
            quantity=1,
            total_amount=100.0,
            currency='INR',
            status='paid',
            product_total=100.0,
            shipping_cost=0.0,
            platform_commission=0.0,
            total_payable=100.0
        )
        
        self.product.delete()
        order.refresh_from_db()
        self.assertIsNone(order.product)
        self.assertIsNotNone(order.buyer)
