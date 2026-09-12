import tempfile
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import User, ArtisanProfile
from listings.models import Product, Category
from frames.models import Reel, ReelLike


class FramesBackendTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create Artisan User
        self.artisan_user = User.objects.create_user(
            username='ramesh_potter',
            email='ramesh@example.com',
            password='Password123!',
            phone='+919876543201',
            role='artisan',
            first_name='Ramesh',
            last_name='Kumar'
        )
        self.artisan_profile = ArtisanProfile.objects.create(
            user=self.artisan_user,
            craft_type='Pottery',
            bio='Master potter with 20 years experience'
        )

        # Create Another Artisan User (for permission tests)
        self.other_artisan_user = User.objects.create_user(
            username='suresh_weaver',
            email='suresh@example.com',
            password='Password123!',
            phone='+919876543202',
            role='artisan',
            first_name='Suresh',
            last_name='Sharma'
        )
        self.other_artisan_profile = ArtisanProfile.objects.create(
            user=self.other_artisan_user,
            craft_type='Weaving',
            bio='Handloom specialist'
        )

        # Create Buyer User
        self.buyer_user = User.objects.create_user(
            username='priya_buyer',
            email='priya@example.com',
            password='Password123!',
            phone='+919876543203',
            role='buyer'
        )


        # Create Category and Product
        self.category = Category.objects.create(name='Terracotta Pottery')
        self.product = Product.objects.create(
            artisan=self.artisan_profile,
            category=self.category,
            title_en='Handmade Terracotta Vase',
            price=1250.00,
            raw_image='products/raw/test.jpg',
            status='live'
        )


        # Create Sample Reel
        dummy_video = SimpleUploadedFile("reel1.mp4", b"fake mp4 video stream bytes", content_type="video/mp4")
        self.reel = Reel.objects.create(
            artisan=self.artisan_profile,
            product=self.product,
            video_file=dummy_video,
            caption="Behind the scenes creating the handmade terracotta vase!",
            view_count=5
        )

    def test_feed_endpoint_unauthenticated(self):
        response = self.client.get('/api/frames/feed/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertTrue(len(results) >= 1)
        item = results[0]
        self.assertEqual(item['caption'], "Behind the scenes creating the handmade terracotta vase!")
        self.assertEqual(item['is_liked_by_me'], False)
        self.assertEqual(item['artisan_name'], "Ramesh Kumar")
        self.assertEqual(item['craft_type'], "Pottery")
        self.assertEqual(item['product_id'], self.product.id)

    def test_feed_endpoint_authenticated_with_like(self):
        # Like the reel as buyer
        ReelLike.objects.create(reel=self.reel, user=self.buyer_user)

        self.client.force_authenticate(user=self.buyer_user)
        response = self.client.get('/api/frames/feed/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        item = [r for r in results if r['id'] == self.reel.id][0]
        self.assertEqual(item['is_liked_by_me'], True)
        self.assertEqual(item['like_count'], 1)

    def test_view_count_increment(self):
        initial_views = self.reel.view_count
        response = self.client.post(f'/api/frames/{self.reel.id}/view/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['view_count'], initial_views + 1)
        self.reel.refresh_from_db()
        self.assertEqual(self.reel.view_count, initial_views + 1)

    def test_like_toggle_functionality(self):
        self.client.force_authenticate(user=self.buyer_user)

        # 1. Like
        res1 = self.client.post(f'/api/frames/{self.reel.id}/like/')
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertTrue(res1.data['is_liked'])
        self.assertEqual(res1.data['like_count'], 1)
        self.assertTrue(ReelLike.objects.filter(reel=self.reel, user=self.buyer_user).exists())

        # 2. Unlike (Toggle)
        res2 = self.client.post(f'/api/frames/{self.reel.id}/like/')
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertFalse(res2.data['is_liked'])
        self.assertEqual(res2.data['like_count'], 0)
        self.assertFalse(ReelLike.objects.filter(reel=self.reel, user=self.buyer_user).exists())

    def test_artisan_upload_success(self):
        self.client.force_authenticate(user=self.artisan_user)
        video_content = SimpleUploadedFile("pottery_craft.mp4", b"video binary data", content_type="video/mp4")
        # Valid 1x1 transparent GIF bytes for ImageField validation
        valid_gif = (
            b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00'
            b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        )
        thumb_content = SimpleUploadedFile("thumb.gif", valid_gif, content_type="image/gif")

        payload = {
            'video_file': video_content,
            'thumbnail': thumb_content,
            'caption': 'Clay moulding session in Mumbai',
            'product_id': self.product.id
        }

        response = self.client.post('/api/frames/upload/', payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['caption'], 'Clay moulding session in Mumbai')
        self.assertEqual(response.data['product_id'], self.product.id)
        self.assertEqual(response.data['artisan_name'], 'Ramesh Kumar')


    def test_buyer_cannot_upload_frame(self):
        self.client.force_authenticate(user=self.buyer_user)
        video_content = SimpleUploadedFile("test.mp4", b"video binary data", content_type="video/mp4")
        payload = {'video_file': video_content, 'caption': 'Should fail'}

        response = self.client.post('/api/frames/upload/', payload, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_artisan_mine_endpoint(self):
        self.client.force_authenticate(user=self.artisan_user)
        response = self.client.get('/api/frames/mine/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.reel.id)

    def test_artisan_stats_endpoint_authorization(self):
        # 1. Owner can view stats
        self.client.force_authenticate(user=self.artisan_user)
        res_owner = self.client.get(f'/api/frames/{self.reel.id}/stats/')
        self.assertEqual(res_owner.status_code, status.HTTP_200_OK)
        self.assertEqual(res_owner.data['total_views'], self.reel.view_count)

        # 2. Different artisan gets 403 Forbidden
        self.client.force_authenticate(user=self.other_artisan_user)
        res_other = self.client.get(f'/api/frames/{self.reel.id}/stats/')
        self.assertEqual(res_other.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Buyer gets 403 Forbidden
        self.client.force_authenticate(user=self.buyer_user)
        res_buyer = self.client.get(f'/api/frames/{self.reel.id}/stats/')
        self.assertEqual(res_buyer.status_code, status.HTTP_403_FORBIDDEN)
