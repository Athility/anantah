from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.cache import cache

class OTPBruteForceSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.phone = "919999999999"
        self.phone2 = "918888888888"
        self.send_url = reverse('send_otp')
        self.verify_url = reverse('verify_otp')
        cache.clear()

    def test_otp_brute_force_lockout(self):
        """A. repeated incorrect OTP attempts are blocked"""
        # 1. Send OTP
        res = self.client.post(self.send_url, {'phone': self.phone})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        dev_otp = res.data.get('dev_otp')

        # 2. Try incorrect OTP 5 times
        for _ in range(5):
            res_verify = self.client.post(self.verify_url, {'phone': self.phone, 'otp': '0000'})
            self.assertEqual(res_verify.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. 6th attempt with CORRECT OTP should fail because it's locked out! (D. correct OTP cannot succeed after the challenge is locked)
        res_locked = self.client.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp})
        self.assertEqual(res_locked.status_code, status.HTTP_400_BAD_REQUEST)

    def test_changing_ip_does_not_reset_counter(self):
        """B. changing IP does not reset the account/challenge attempt counter"""
        res = self.client.post(self.send_url, {'phone': self.phone})
        dev_otp = res.data.get('dev_otp')

        # Try from different IPs
        for i in range(5):
            # We simulate different IPs by changing the REMOTE_ADDR
            client = APIClient(REMOTE_ADDR=f"192.168.1.{i}")
            res_verify = client.post(self.verify_url, {'phone': self.phone, 'otp': '0000'})
            self.assertEqual(res_verify.status_code, status.HTTP_400_BAD_REQUEST)

        # 6th attempt with different IP and correct OTP should fail
        client_new = APIClient(REMOTE_ADDR="10.0.0.1")
        res_locked = client_new.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp})
        self.assertEqual(res_locked.status_code, status.HTTP_400_BAD_REQUEST)

    def test_correct_otp_succeeds_before_limit(self):
        """C. correct OTP succeeds before the limit"""
        res = self.client.post(self.send_url, {'phone': self.phone})
        dev_otp = res.data.get('dev_otp')

        # 3 incorrect
        for _ in range(3):
            self.client.post(self.verify_url, {'phone': self.phone, 'otp': '0000'})

        # 4th correct
        res_verify = self.client.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp})
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)

    def test_successful_verification_invalidates_otp(self):
        """E. successful verification invalidates/retires the OTP"""
        res = self.client.post(self.send_url, {'phone': self.phone})
        dev_otp = res.data.get('dev_otp')

        # 1st attempt correct
        res_verify = self.client.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp})
        self.assertEqual(res_verify.status_code, status.HTTP_200_OK)

        # 2nd attempt with same correct OTP should fail
        res_verify2 = self.client.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp})
        self.assertEqual(res_verify2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_separate_users_do_not_share_counter(self):
        """F. separate users/challenges do not share the same attempt counter"""
        res1 = self.client.post(self.send_url, {'phone': self.phone})
        dev_otp1 = res1.data.get('dev_otp')

        # bypass 30s lock for second phone by just using phone2
        res2 = self.client.post(self.send_url, {'phone': self.phone2})
        dev_otp2 = res2.data.get('dev_otp')

        # Fail 5 times on phone1
        for _ in range(5):
            self.client.post(self.verify_url, {'phone': self.phone, 'otp': '0000'})

        # phone1 is locked out
        self.assertEqual(self.client.post(self.verify_url, {'phone': self.phone, 'otp': dev_otp1}).status_code, status.HTTP_400_BAD_REQUEST)

        # phone2 is not affected
        res_verify2 = self.client.post(self.verify_url, {'phone': self.phone2, 'otp': dev_otp2})
        self.assertEqual(res_verify2.status_code, status.HTTP_200_OK)

    def test_otp_send_throttling_intact(self):
        """G. existing OTP send throttling remains intact"""
        res = self.client.post(self.send_url, {'phone': self.phone})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Immediate resend should be blocked by 30s lock
        res2 = self.client.post(self.send_url, {'phone': self.phone})
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)
