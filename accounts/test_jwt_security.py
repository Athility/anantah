from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
from django.core.cache import cache

User = get_user_model()

class JWTSecurityTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='buyer', phone='1234567890', password='password123', role='buyer')
        self.artisan = User.objects.create_user(username='artisan', phone='0987654321', password='password123', role='artisan')
        
    def test_a_valid_access_token_works(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        res = self.client.get('/api/accounts/me/')
        self.assertEqual(res.status_code, 200)

    def test_b_expired_access_token_fails(self):
        from datetime import timedelta
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        access.set_exp(lifetime=timedelta(seconds=-1))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        res = self.client.get('/api/accounts/me/')
        self.assertEqual(res.status_code, 401)

    def test_c_valid_refresh_token_obtains_new_access_and_rotates(self):
        refresh = RefreshToken.for_user(self.user)
        res = self.client.post('/api/accounts/login/refresh/', {'refresh': str(refresh)})
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data) # rotation is enabled

    def test_d_logged_out_refresh_token_fails(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        res = self.client.post('/api/accounts/logout/', {'refresh': str(refresh)})
        self.assertEqual(res.status_code, 200)
        
        # Try to use refresh token
        res_refresh = self.client.post('/api/accounts/login/refresh/', {'refresh': str(refresh)})
        self.assertEqual(res_refresh.status_code, 401)

    def test_f_rotated_old_refresh_token_cannot_be_reused(self):
        refresh = RefreshToken.for_user(self.user)
        res = self.client.post('/api/accounts/login/refresh/', {'refresh': str(refresh)})
        self.assertEqual(res.status_code, 200)
        
        # Old refresh token is blacklisted!
        res_refresh = self.client.post('/api/accounts/login/refresh/', {'refresh': str(refresh)})
        self.assertEqual(res_refresh.status_code, 401)

    def test_password_reset_revokes_tokens(self):
        refresh = RefreshToken.for_user(self.user)
        # Verify outstanding tokens populated
        # NOTE: SimpleJWT automatically creates OutstandingToken during RefreshToken.for_user? Yes, if configured, wait, we need to check if it does.
        # Actually, let's just make sure it fails after reset.
        
        # Reset password
        cache.set(f"phone_verified:{self.user.phone}", True, timeout=900)
        cache.set(f"otp_attempts_{self.user.phone}", 0, timeout=900)
        from accounts.otp_service import generate_and_send_otp
        generate_and_send_otp(self.user.phone)
        otp = cache.get(f"otp:{self.user.phone}")
        
        res = self.client.post('/api/accounts/password-reset/confirm/', {
            'phone': self.user.phone,
            'otp': otp,
            'new_password': 'newpassword123'
        })
        self.assertEqual(res.status_code, 200)
        
        # Try to use old refresh token
        res_refresh = self.client.post('/api/accounts/login/refresh/', {'refresh': str(refresh)})
        self.assertEqual(res_refresh.status_code, 401)

    def test_g_invalid_refresh_token_fails_safely(self):
        res = self.client.post('/api/accounts/login/refresh/', {'refresh': 'invalid_token_string'})
        self.assertEqual(res.status_code, 401)

    def test_h_malformed_token_fails_safely(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer malformed.token.string')
        res = self.client.get('/api/accounts/me/')
        self.assertEqual(res.status_code, 401)

    def test_i_buyer_cannot_access_artisan(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        res = self.client.post('/api/listings/upload/', {}) # Artisan only
        self.assertEqual(res.status_code, 403)

    def test_j_artisan_cannot_access_buyer(self):
        refresh = RefreshToken.for_user(self.artisan)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        res = self.client.post('/api/orders/create/', {}) # Buyer only
        self.assertEqual(res.status_code, 403)
