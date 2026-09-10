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
            status='live'
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
        p2 = Product.objects.create(artisan=self.artisan_profile, title_en='Product 2', price=50.0, status='live')
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        CartItem.objects.create(buyer=self.buyer_profile, product=p2, quantity=1)
        
        mock_create.side_effect = Exception('Razorpay API down')
        
        response = self.client.post('/api/orders/create/', {'address_id': self.address.id}, format='json')
        print("RESPONSE STATUS:", response.status_code)
        print("RESPONSE DATA:", response.data)
        
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(Order.objects.count(), 2)
        self.assertTrue(all(o.status == 'cancelled' for o in Order.objects.all()))
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

    @mock.patch('cart.views.create_razorpay_order')
    def test_checkout_with_existing_order_having_null_product(self, mock_create):
        mock_create.return_value = {
            'id': 'order_rzp_test_123',
            'amount': 18500,
            'currency': 'INR',
            'status': 'created'
        }
        # Create an existing order in 'created' status with null product
        Order.objects.create(
            buyer=self.buyer_profile,
            product=None,
            artisan=self.artisan_profile,
            shipping_address=self.address,
            quantity=1,
            total_amount=100.0,
            currency='INR',
            status='created',
            product_total=100.0,
            shipping_cost=0.0,
            platform_commission=0.0,
            total_payable=100.0
        )
        # Put an item in the cart
        CartItem.objects.create(buyer=self.buyer_profile, product=self.product, quantity=1)
        
        response = self.client.post('/api/orders/create/', {'address_id': self.address.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['razorpay_order_id'], 'order_rzp_test_123')


