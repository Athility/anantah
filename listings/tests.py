from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import User
from listings.models import Product

class UploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='artisan1', phone='1111111111', password='pass', role='artisan')
        self.client = APIClient()
        from accounts.models import ArtisanProfile
        ArtisanProfile.objects.get_or_create(user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_invalid_file_upload(self):
        fake_php = SimpleUploadedFile('shell.php', b'<?php echo "hack"; ?>', content_type='application/x-php')
        
        data = {
            'title_en': 'Hacked Product',
            'price': '500',
            'raw_image': fake_php,
        }
        
        response = self.client.post('/api/listings/upload/', data, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Product.objects.count(), 0)

    def test_valid_image_upload(self):
        import io
        from PIL import Image
        from unittest import mock
        
        file_obj = io.BytesIO()
        image = Image.new('RGB', (10, 10), 'white')
        image.save(file_obj, 'JPEG')
        file_obj.seek(0)
        
        valid_image = SimpleUploadedFile('test.jpg', file_obj.read(), content_type='image/jpeg')
        
        data = {
            'title_en': 'Good Product',
            'price': '500',
            'raw_image': valid_image,
        }
        
        with mock.patch('listings.views.refine_image') as mock_refine:
            file_obj.seek(0)
            mock_refine.return_value = file_obj
            response = self.client.post('/api/listings/upload/', data, format='multipart')
            if response.status_code != 201: print('ERROR:', response.content)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(Product.objects.count(), 1)
            # Verify initial status is draft
            self.assertEqual(Product.objects.first().status, 'draft')

    def test_product_lifecycle_draft_to_live(self):
        import io
        from PIL import Image
        from unittest import mock
        
        file_obj = io.BytesIO()
        image = Image.new('RGB', (10, 10), 'white')
        image.save(file_obj, 'JPEG')
        file_obj.seek(0)
        valid_image = SimpleUploadedFile('craft.jpg', file_obj.read(), content_type='image/jpeg')
        
        data = {
            'title_en': 'Draft Handicraft',
            'price': '750',
            'raw_image': valid_image,
        }
        
        with mock.patch('listings.views.refine_image') as mock_refine:
            file_obj.seek(0)
            mock_refine.return_value = file_obj
            res = self.client.post('/api/listings/upload/', data, format='multipart')
            self.assertEqual(res.status_code, status.HTTP_201_CREATED)
            product_id = res.data['id']
            
        product = Product.objects.get(id=product_id)
        self.assertEqual(product.status, 'draft')
        
        # Buyer should NOT see draft product in public listings
        buyer_user = User.objects.create_user(username='buyer_user_1', phone='3333333333', password='pass', role='buyer')
        self.client.force_authenticate(user=buyer_user)
        res_buyer = self.client.get('/api/listings/upload/')
        self.assertEqual(res_buyer.status_code, status.HTTP_200_OK)
        self.assertFalse(any(p['id'] == product_id for p in res_buyer.data))
        
        # Artisan confirms catalog
        self.client.force_authenticate(user=self.user)
        confirm_res = self.client.patch(f'/api/listings/{product_id}/confirm-catalog/', {
            'title_en': 'Published Handicraft',
            'description_en': 'Finest handmade craft.',
            'title_hi': 'हस्तशिल्प',
            'description_hi': 'सुंदर हस्तशिल्प।'
        }, format='json')
        self.assertEqual(confirm_res.status_code, status.HTTP_200_OK)
        self.assertEqual(confirm_res.data['status'], 'live')
        
        # Now buyer sees the live product
        self.client.force_authenticate(user=buyer_user)
        res_buyer_after = self.client.get('/api/listings/upload/')
        self.assertTrue(any(p['id'] == product_id for p in res_buyer_after.data))

    def test_safe_file_cleanup_on_delete(self):
        import io
        from PIL import Image
        from unittest import mock
        
        file_obj = io.BytesIO()
        image = Image.new('RGB', (10, 10), 'white')
        image.save(file_obj, 'JPEG')
        file_obj.seek(0)
        valid_image = SimpleUploadedFile('craft_del.jpg', file_obj.read(), content_type='image/jpeg')
        
        with mock.patch('listings.views.refine_image') as mock_refine:
            file_obj.seek(0)
            mock_refine.return_value = file_obj
            res = self.client.post('/api/listings/upload/', {
                'title_en': 'To Delete',
                'price': '300',
                'raw_image': valid_image
            }, format='multipart')
            product_id = res.data['id']
            
        product = Product.objects.get(id=product_id)
        
        # Simulate PermissionError on os.remove when deleting product
        with mock.patch('os.remove', side_effect=PermissionError('File locked by another process')):
            product.delete()
            self.assertEqual(Product.objects.filter(id=product_id).count(), 0)

    def test_remote_storage_cleanup_not_implemented_error(self):
        """Verify delete_product_files safely handles storage backends where field.path raises NotImplementedError."""
        from unittest import mock
        from accounts.models import ArtisanProfile

        artisan_profile = ArtisanProfile.objects.get(user=self.user)
        product = Product.objects.create(
            artisan=artisan_profile,
            title_en="Remote Product",
            price=150.00,
            raw_image="media/products/raw/remote_sample",
            refined_image="media/products/refined/remote_refined",
            raw_audio="media/products/audio/remote_audio",
            status="live"
        )

        with mock.patch('django.db.models.fields.files.FieldFile.path', new_callable=mock.PropertyMock) as mock_path:
            mock_path.side_effect = NotImplementedError("Remote storage does not support local paths")
            # Deletion should complete cleanly without error
            product.delete()
            self.assertEqual(Product.objects.filter(id=product.id).count(), 0)

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            "audio": {"BACKEND": "cloudinary_storage.storage.VideoMediaCloudinaryStorage"},
        }
    )
    def test_serializer_returns_https_cloudinary_urls(self):
        """Verify ProductSerializer produces absolute HTTPS URLs for Cloudinary-hosted assets."""
        from listings.serializers import ProductSerializer
        from accounts.models import ArtisanProfile
        from cloudinary_storage.storage import VideoMediaCloudinaryStorage, MediaCloudinaryStorage
        from unittest import mock

        artisan_profile = ArtisanProfile.objects.get(user=self.user)
        with mock.patch.object(Product._meta.get_field('raw_audio'), 'storage', VideoMediaCloudinaryStorage()), \
             mock.patch.object(Product._meta.get_field('raw_image'), 'storage', MediaCloudinaryStorage()), \
             mock.patch.object(Product._meta.get_field('refined_image'), 'storage', MediaCloudinaryStorage()):
            
            product = Product.objects.create(
                artisan=artisan_profile,
                title_en="Cloud Product",
                price=299.99,
                raw_image="products/raw/vase_123.jpg",
                refined_image="products/refined/refined_vase_123.jpg",
                raw_audio="products/audio/voice_vase_123.webm",
                status="live"
            )

            serializer = ProductSerializer(product)
            data = serializer.data
            self.assertIsNotNone(data['raw_image_url'])
            self.assertIsNotNone(data['refined_image_url'])
            self.assertIsNotNone(data['raw_audio_url'])
            self.assertTrue(data['raw_image_url'].startswith('https://res.cloudinary.com/'))
            self.assertTrue(data['refined_image_url'].startswith('https://res.cloudinary.com/'))
            self.assertTrue(data['raw_audio_url'].startswith('https://res.cloudinary.com/'))

    @override_settings(
        STORAGES={
            "default": {"BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            "audio": {"BACKEND": "cloudinary_storage.storage.VideoMediaCloudinaryStorage"},
        }
    )
    def test_migrate_command_dry_run_execution(self):
        """Verify migrate_media_to_cloudinary command runs successfully in dry-run mode."""
        from io import StringIO
        from django.core.management import call_command

        out = StringIO()
        call_command('migrate_media_to_cloudinary', '--dry-run', stdout=out)
        output = out.getvalue()
        self.assertIn("Anantah Cloudinary Media Migration", output)
        self.assertIn("Mode: DRY-RUN", output)
        self.assertIn("Migration Summary", output)


class PublicCatalogAndGuestBrowsingTests(TestCase):
    def setUp(self):
        from accounts.models import ArtisanProfile, BuyerProfile
        self.client = APIClient()
        self.artisan_user = User.objects.create_user(username='artisan_seller', phone='1234567891', password='pass', role='artisan')
        self.artisan_profile, _ = ArtisanProfile.objects.get_or_create(user=self.artisan_user)

        self.buyer_user = User.objects.create_user(username='buyer_shopper', phone='1234567892', password='pass', role='buyer')
        self.buyer_profile, _ = BuyerProfile.objects.get_or_create(user=self.buyer_user)

        # Products with varying statuses
        self.live_product = Product.objects.create(
            artisan=self.artisan_profile,
            title_en="Live Terracotta Pot",
            price=350.0,
            status="live"
        )
        self.draft_product = Product.objects.create(
            artisan=self.artisan_profile,
            title_en="Draft Clay Pot",
            price=200.0,
            status="draft"
        )
        self.flagged_product = Product.objects.create(
            artisan=self.artisan_profile,
            title_en="Flagged Item",
            price=100.0,
            status="flagged"
        )

    def test_anonymous_get_listings_success(self):
        """Anonymous guest request to GET /api/listings/upload/ must succeed with 200."""
        response = self.client.get('/api/listings/upload/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.live_product.id)

    def test_anonymous_get_listings_excludes_draft_and_flagged(self):
        """Anonymous guest request must only see live products, not draft or flagged."""
        response = self.client.get('/api/listings/upload/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [p['id'] for p in response.json()]
        self.assertIn(self.live_product.id, returned_ids)
        self.assertNotIn(self.draft_product.id, returned_ids)
        self.assertNotIn(self.flagged_product.id, returned_ids)

    def test_anonymous_post_listings_rejected(self):
        """Anonymous guest request to POST /api/listings/upload/ must be rejected with 401."""
        response = self.client.post('/api/listings/upload/', {'title_en': 'Unauthorized'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_buyer_post_listings_forbidden(self):
        """Authenticated buyer attempting to upload a product must receive 403 Forbidden."""
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.post('/api/listings/upload/', {'title_en': 'Buyer Trying Upload'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_buyer_get_listings(self):
        """Authenticated buyer receives all live products."""
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get('/api/listings/upload/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [p['id'] for p in response.json()]
        self.assertIn(self.live_product.id, returned_ids)
        self.assertNotIn(self.draft_product.id, returned_ids)

    def test_authenticated_artisan_get_listings(self):
        """Authenticated artisan receives all their own products regardless of status."""
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/upload/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [p['id'] for p in response.json()]
        self.assertIn(self.live_product.id, returned_ids)
        self.assertIn(self.draft_product.id, returned_ids)


