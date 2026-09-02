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
