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


# ─────────────────────────────────────────────────────────────────────────────
# Analytics Tests
# ─────────────────────────────────────────────────────────────────────────────

from decimal import Decimal
from accounts.models import ArtisanProfile, BuyerProfile
from cart.models import Order, Address


def _make_address(user):
    """Helper: create a minimal Address for Order creation."""
    return Address.objects.create(
        user=user,
        full_name='Test Buyer',
        phone='9999999999',
        line1='1 Test Street',
        city='Mumbai',
        state='Maharashtra',
        postal_code='400001',
    )


class AnalyticsTests(TestCase):
    """
    12 regression tests for GET /api/listings/analytics/ and
    POST /api/listings/<id>/view/.

    Covers: authentication, role enforcement, artisan isolation (IDOR),
    revenue filtering by order status, view counting accuracy, empty states,
    and absence of private buyer data in responses.
    """

    def setUp(self):
        self.client = APIClient()

        # ── Artisan A ────────────────────────────────────────────────────────
        self.artisan_user = User.objects.create_user(
            username='artisan_ana', phone='1010101010', password='pass', role='artisan'
        )
        self.artisan_profile = ArtisanProfile.objects.create(user=self.artisan_user)

        # ── Artisan B (another artisan — used for isolation tests) ───────────
        self.artisan_user_b = User.objects.create_user(
            username='artisan_bob', phone='2020202020', password='pass', role='artisan'
        )
        self.artisan_profile_b = ArtisanProfile.objects.create(user=self.artisan_user_b)

        # ── Buyer ────────────────────────────────────────────────────────────
        self.buyer_user = User.objects.create_user(
            username='buyer_bina', phone='3030303030', password='pass', role='buyer'
        )
        self.buyer_profile = BuyerProfile.objects.create(user=self.buyer_user)
        self.address = _make_address(self.buyer_user)

        # ── Artisan A's products ──────────────────────────────────────────────
        self.product_a1 = Product.objects.create(
            artisan=self.artisan_profile,
            title_en='Vase A1',
            price=Decimal('400.00'),
            raw_image='products/raw/test.jpg',
            status='live',
            view_count=10,
        )
        self.product_a2 = Product.objects.create(
            artisan=self.artisan_profile,
            title_en='Basket A2',
            price=Decimal('250.00'),
            raw_image='products/raw/test2.jpg',
            status='live',
            view_count=5,
        )

        # ── Artisan B's product ───────────────────────────────────────────────
        self.product_b1 = Product.objects.create(
            artisan=self.artisan_profile_b,
            title_en='Bowl B1',
            price=Decimal('300.00'),
            raw_image='products/raw/test3.jpg',
            status='live',
        )

    def _make_order(self, artisan_profile, product, status_val, amount='400.00'):
        return Order.objects.create(
            buyer=self.buyer_profile,
            product=product,
            artisan=artisan_profile,
            shipping_address=self.address,
            quantity=1,
            total_amount=Decimal(amount),
            product_total=Decimal(amount),
            status=status_val,
        )

    # ── Test 1 ───────────────────────────────────────────────────────────────
    def test_1_authenticated_artisan_can_access_analytics(self):
        """Artisan gets HTTP 200 and correct top-level keys."""
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn('summary', data)
        self.assertIn('products', data)
        self.assertIn('recent_orders', data)

    # ── Test 2 ───────────────────────────────────────────────────────────────
    def test_2_buyer_cannot_access_analytics(self):
        """Buyer receives HTTP 403."""
        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # ── Test 3 ───────────────────────────────────────────────────────────────
    def test_3_unauthenticated_cannot_access_analytics(self):
        """Unauthenticated request receives HTTP 401."""
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ── Test 4 ───────────────────────────────────────────────────────────────
    def test_4_artisan_only_sees_own_products(self):
        """Artisan A's analytics products list does not include Artisan B's product."""
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        product_ids = [p['id'] for p in response.json()['products']]
        self.assertIn(self.product_a1.id, product_ids)
        self.assertIn(self.product_a2.id, product_ids)
        self.assertNotIn(self.product_b1.id, product_ids)

    # ── Test 5 ───────────────────────────────────────────────────────────────
    def test_5_artisan_only_sees_own_orders(self):
        """Artisan A's recent_orders does not include Artisan B's orders."""
        order_a = self._make_order(self.artisan_profile, self.product_a1, 'paid')
        order_b = self._make_order(self.artisan_profile_b, self.product_b1, 'paid')

        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        order_ids = [o['id'] for o in response.json()['recent_orders']]
        self.assertIn(order_a.id, order_ids)
        self.assertNotIn(order_b.id, order_ids)

    # ── Test 6 ───────────────────────────────────────────────────────────────
    def test_6_revenue_excludes_cancelled_orders(self):
        """Cancelled orders do not contribute to total_revenue."""
        self._make_order(self.artisan_profile, self.product_a1, 'cancelled', '400.00')
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.json()['summary']['total_revenue'], '0.00')

    # ── Test 7 ───────────────────────────────────────────────────────────────
    def test_7_revenue_excludes_payment_failed_orders(self):
        """payment_failed orders do not contribute to total_revenue."""
        self._make_order(self.artisan_profile, self.product_a1, 'payment_failed', '400.00')
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.json()['summary']['total_revenue'], '0.00')

    # ── Test 8 ───────────────────────────────────────────────────────────────
    def test_8_revenue_excludes_created_unpaid_orders(self):
        """'created' (unpaid) orders do not contribute to total_revenue."""
        self._make_order(self.artisan_profile, self.product_a1, 'created', '400.00')
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.json()['summary']['total_revenue'], '0.00')

    # ── Test 9 ───────────────────────────────────────────────────────────────
    def test_9_multi_artisan_revenue_attributed_to_correct_artisan(self):
        """
        When orders from two artisans exist, each artisan only sees
        their own product_total in total_revenue.
        """
        self._make_order(self.artisan_profile,   self.product_a1, 'paid', '400.00')
        self._make_order(self.artisan_profile_b, self.product_b1, 'paid', '300.00')

        self.client.force_authenticate(user=self.artisan_user)
        resp_a = self.client.get('/api/listings/analytics/')
        self.assertEqual(resp_a.json()['summary']['total_revenue'], '400.00')

        self.client.force_authenticate(user=self.artisan_user_b)
        resp_b = self.client.get('/api/listings/analytics/')
        self.assertEqual(resp_b.json()['summary']['total_revenue'], '300.00')

    # ── Test 10 ──────────────────────────────────────────────────────────────
    def test_10_product_view_count_increments(self):
        """POST /api/listings/<id>/view/ atomically increments view_count for live products."""
        initial = self.product_a1.view_count  # 10 from setUp
        response = self.client.post(f'/api/listings/{self.product_a1.id}/view/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product_a1.refresh_from_db()
        self.assertEqual(self.product_a1.view_count, initial + 1)

    # ── Test 11 ──────────────────────────────────────────────────────────────
    def test_11_empty_artisan_returns_valid_zero_analytics(self):
        """An artisan with no products returns a valid response with zero values."""
        empty_user = User.objects.create_user(
            username='artisan_empty', phone='4040404040', password='pass', role='artisan'
        )
        ArtisanProfile.objects.create(user=empty_user)
        self.client.force_authenticate(user=empty_user)
        response = self.client.get('/api/listings/analytics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.json()['summary']
        self.assertEqual(summary['total_listings'], 0)
        self.assertEqual(summary['total_views'], 0)
        self.assertEqual(summary['total_orders'], 0)
        self.assertEqual(summary['total_revenue'], '0.00')
        self.assertEqual(response.json()['products'], [])
        self.assertEqual(response.json()['recent_orders'], [])

    # ── Test 12 ──────────────────────────────────────────────────────────────
    def test_12_recent_orders_do_not_expose_buyer_private_info(self):
        """recent_orders must not contain buyer phone, address, or payment secrets."""
        self._make_order(self.artisan_profile, self.product_a1, 'paid')
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/listings/analytics/')
        for order in response.json()['recent_orders']:
            self.assertNotIn('phone', order)
            self.assertNotIn('buyer_phone', order)
            self.assertNotIn('shipping_address', order)
            self.assertNotIn('razorpay_payment_id', order)
            self.assertNotIn('razorpay_order_id', order)
            self.assertNotIn('buyer', order)
            # Permitted fields only
            expected_keys = {'id', 'product_title', 'quantity', 'amount', 'status', 'created_at'}
            self.assertEqual(set(order.keys()), expected_keys)
