from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User, ArtisanProfile, BuyerProfile
from listings.models import Product
from wishlist.models import WishlistItem

class WishlistAPITestCase(TestCase):
    def setUp(self):
        # Create Buyer User & Profile
        self.buyer_user = User.objects.create_user(
            username='buyer_test',
            password='password123',
            role='buyer',
            phone='+919876543210'
        )
        self.buyer_profile = BuyerProfile.objects.create(user=self.buyer_user)

        # Create Artisan User & Profile
        self.artisan_user = User.objects.create_user(
            username='artisan_test',
            password='password123',
            role='artisan',
            phone='+919876543211'
        )
        self.artisan_profile = ArtisanProfile.objects.create(user=self.artisan_user, craft_type='Pottery')

        # Create Product
        self.product = Product.objects.create(
            artisan=self.artisan_profile,
            title_en='Handcrafted Terracotta Vase',
            price=499.00,
            status='live'
        )

        self.client = APIClient()

    def test_buyer_can_add_to_wishlist(self):
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post('/api/wishlist/add/', {'product_id': self.product.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['product_id'], self.product.id)
        self.assertTrue(WishlistItem.objects.filter(buyer=self.buyer_profile, product=self.product).exists())

    def test_duplicate_add_returns_200_clean_response(self):
        self.client.force_authenticate(user=self.buyer_user)
        self.client.post('/api/wishlist/add/', {'product_id': self.product.id}, format='json')
        response = self.client.post('/api/wishlist/add/', {'product_id': self.product.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'Already in wishlist.')
        self.assertEqual(WishlistItem.objects.filter(buyer=self.buyer_profile, product=self.product).count(), 1)

    def test_buyer_can_list_wishlist(self):
        self.client.force_authenticate(user=self.buyer_user)
        WishlistItem.objects.create(buyer=self.buyer_profile, product=self.product)
        response = self.client.get('/api/wishlist/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['product']['title_en'], 'Handcrafted Terracotta Vase')
        self.assertEqual(response.data[0]['product']['artisan_name'], 'artisan_test')

    def test_buyer_can_check_wishlist_status(self):
        self.client.force_authenticate(user=self.buyer_user)
        item = WishlistItem.objects.create(buyer=self.buyer_profile, product=self.product)
        response = self.client.get(f'/api/wishlist/check/{self.product.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_wishlisted'])
        self.assertEqual(response.data['item_id'], item.id)

    def test_buyer_can_delete_wishlist_item(self):
        self.client.force_authenticate(user=self.buyer_user)
        item = WishlistItem.objects.create(buyer=self.buyer_profile, product=self.product)
        response = self.client.delete(f'/api/wishlist/{item.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(WishlistItem.objects.filter(id=item.id).exists())

    def test_artisan_cannot_access_wishlist(self):
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/wishlist/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
