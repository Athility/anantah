from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User, ArtisanProfile
from listings.models import Product

class CatalogConfirmationSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='artisan1', phone='919999999991', role='artisan')
        self.artisan = ArtisanProfile.objects.create(user=self.user)
        self.product = Product.objects.create(
            artisan=self.artisan,
            title_en='Test Product',
            price=10.00,
            status='draft',
            raw_image='dummy.jpg'
        )
        self.url = reverse('confirm_catalog', kwargs={'product_id': self.product.id})
        self.client.force_authenticate(user=self.user)

    def test_normal_catalog_confirmation_succeeds(self):
        """A. normal catalog confirmation still succeeds"""
        res = self.client.patch(self.url, {'title_en': 'Updated Title', 'description_en': 'Good info'})
        print("RESPONSE:", res.data)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.title_en, 'Updated Title')
        self.assertEqual(self.product.status, 'live')

    def test_description_en_over_max_length_rejected(self):
        """B. description_en over max length is rejected cleanly"""
        huge_desc = 'a' * 10001
        res = self.client.patch(self.url, {'description_en': huge_desc})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.product.refresh_from_db()
        self.assertNotEqual(self.product.description_en, huge_desc)

    def test_title_fields_over_max_length_rejected(self):
        """D. title fields cannot exceed their declared limits"""
        huge_title = 'a' * 201
        res = self.client.patch(self.url, {'title_en': huge_title})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
