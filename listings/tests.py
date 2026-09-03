from django.test import TestCase
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

