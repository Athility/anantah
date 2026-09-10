import io
from PIL import Image
from unittest import mock
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework import status
from accounts.models import User, ArtisanProfile, BuyerProfile
from listings.models import Product
from anantah_core.utils import build_public_media_url


class DeploymentArchitectureTests(TestCase):
    def setUp(self):
        self.artisan_user = User.objects.create_user(
            username='artisan_dep',
            phone='9999900001',
            password='Password123!',
            role='artisan'
        )
        self.artisan_profile = ArtisanProfile.objects.create(user=self.artisan_user, craft_type='Pottery')

        self.buyer_user = User.objects.create_user(
            username='buyer_dep',
            phone='9999900002',
            password='Password123!',
            role='buyer'
        )
        self.buyer_profile = BuyerProfile.objects.create(user=self.buyer_user)

        self.client = APIClient()

    def _create_dummy_image(self, name='test.jpg', size=(50, 50), fmt='JPEG'):
        bio = io.BytesIO()
        img = Image.new('RGB', size, color='blue')
        img.save(bio, format=fmt)
        bio.seek(0)
        return SimpleUploadedFile(name, bio.read(), content_type=f'image/{fmt.lower()}')

    # 1. Settings & Headers
    def test_cors_allow_all_origins_is_false(self):
        self.assertFalse(settings.CORS_ALLOW_ALL_ORIGINS)

    def test_allowed_hosts_includes_cloudflare_and_local(self):
        self.assertTrue(
            '.trycloudflare.com' in settings.ALLOWED_HOSTS or '*' in settings.ALLOWED_HOSTS,
            "ALLOWED_HOSTS should include .trycloudflare.com or *"
        )
        self.assertTrue(
            '127.0.0.1' in settings.ALLOWED_HOSTS or '*' in settings.ALLOWED_HOSTS,
            "ALLOWED_HOSTS should include 127.0.0.1"
        )

    def test_reverse_proxy_ssl_header_configured(self):
        self.assertEqual(settings.SECURE_PROXY_SSL_HEADER, ('HTTP_X_FORWARDED_PROTO', 'https'))
        self.assertTrue(settings.USE_X_FORWARDED_HOST)

    # 2. Role Authorization on Upload
    def test_buyer_cannot_upload_product(self):
        self.client.force_authenticate(user=self.buyer_user)
        img = self._create_dummy_image()
        response = self.client.post('/api/listings/upload/', {
            'title_en': 'Unauthorized Craft',
            'price': '100.00',
            'raw_image': img
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("Only artisans", response.data.get('detail', ''))

    # 3. File Size Limits
    def test_upload_rejects_oversized_image(self):
        self.client.force_authenticate(user=self.artisan_user)
        # Create a file report size > 10MB
        big_content = b'0' * (10 * 1024 * 1024 + 1)
        oversized_file = SimpleUploadedFile('huge.jpg', big_content, content_type='image/jpeg')
        response = self.client.post('/api/listings/upload/', {
            'title_en': 'Oversized Craft',
            'price': '100.00',
            'raw_image': oversized_file
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('raw_image', response.data)
        self.assertIn('10MB', str(response.data['raw_image']))

    # 4. Invalid File Extensions
    def test_upload_rejects_disallowed_extension(self):
        self.client.force_authenticate(user=self.artisan_user)
        fake_file = SimpleUploadedFile('script.exe', b'malicious data', content_type='application/octet-stream')
        response = self.client.post('/api/listings/upload/', {
            'title_en': 'Malicious Craft',
            'price': '100.00',
            'raw_image': fake_file
        }, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # 5. UUID Filename Uniqueness & Sanitization
    @mock.patch('listings.views.refine_image')
    def test_upload_generates_unique_uuid_filenames(self, mock_refine):
        self.client.force_authenticate(user=self.artisan_user)
        dummy_io = io.BytesIO()
        Image.new('RGB', (10, 10), 'white').save(dummy_io, 'JPEG')
        dummy_io.seek(0)
        mock_refine.return_value = dummy_io

        img = self._create_dummy_image(name='../../traversal_test.jpg')
        response = self.client.post('/api/listings/upload/', {
            'title_en': 'Safe Craft',
            'price': '250.00',
            'raw_image': img
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        product = Product.objects.get(id=response.data['id'])

        # Check raw image name is sanitized and starts with raw_ and has no path traversal
        self.assertTrue(product.raw_image.name.startswith('products/raw/raw_'))
        self.assertNotIn('..', product.raw_image.name)
        # Check refined image name starts with refined_
        self.assertTrue(product.refined_image.name.startswith('products/refined/refined_'))

    # 6. Public Media URL Helper
    @override_settings(PUBLIC_API_URL='https://api.anantah.com')
    def test_build_public_media_url_with_public_api_setting(self):
        result = build_public_media_url('/media/products/refined/sample.jpg')
        self.assertEqual(result, 'https://api.anantah.com/media/products/refined/sample.jpg')

    @override_settings(PUBLIC_API_URL='https://api.anantah.com')
    def test_build_public_media_url_rewrites_localhost(self):
        result = build_public_media_url('http://127.0.0.1:8000/media/products/sample.jpg')
        self.assertEqual(result, 'https://api.anantah.com/media/products/sample.jpg')

    @override_settings(PUBLIC_API_URL='https://api.anantah.com')
    def test_build_public_media_url_leaves_external_cdns_intact(self):
        cloudinary_url = 'https://res.cloudinary.com/anantah/image/upload/sample.jpg'
        result = build_public_media_url(cloudinary_url)
        self.assertEqual(result, cloudinary_url)

    # 7. AI Refinement Error Handling
    @mock.patch('listings.views.refine_image')
    def test_refinement_failure_returns_422_and_cleans_up(self, mock_refine):
        self.client.force_authenticate(user=self.artisan_user)
        mock_refine.side_effect = RuntimeError("OpenCV processing crashed")

        img = self._create_dummy_image()
        initial_count = Product.objects.count()
        response = self.client.post('/api/listings/upload/', {
            'title_en': 'Failing Craft',
            'price': '50.00',
            'raw_image': img
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn("AI Image refinement failed", response.data.get('detail', ''))
        # Ensure partial product was deleted
        self.assertEqual(Product.objects.count(), initial_count)
