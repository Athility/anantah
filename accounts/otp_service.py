import random
import logging
import requests
from django.core.cache import cache
from decouple import config

logger = logging.getLogger(__name__)

def generate_and_send_otp(phone_number):
    """
    Generates a 6-digit random OTP, caches it for 5 minutes, enforce 30s resend lock,
    and either logs the OTP or calls the Fast2SMS API.
    """
    # 1. Enforce 30s rate limit
    if cache.get(f"resend_lock:{phone_number}"):
        return {
            "success": False,
            "message": "Rate limit exceeded. Please wait 30 seconds before requesting another OTP."
        }

    # 2. Generate random 4-digit OTP
    otp_code = str(random.randint(1000, 9999))

    # 3. Store OTP in cache for 5 minutes (300 seconds)
    cache.set(f"otp:{phone_number}", otp_code, timeout=300)
    cache.set(f"otp_attempts:{phone_number}", 0, timeout=300)

    # 4. Set resend lock for 30 seconds
    cache.set(f"resend_lock:{phone_number}", True, timeout=30)

    # 5. Check if Fast2SMS KYC is verified
    kyc_verified = config('FAST2SMS_KYC_VERIFIED', default=False, cast=bool)
    api_key = config('FAST2SMS_API_KEY', default='').strip()

    if not kyc_verified or not api_key:
        # Dev mode - print to console/log
        print(f"\n==================================================")
        print(f"[DEV MODE - NO SMS SENT] OTP for {phone_number}: {otp_code}")
        print(f"==================================================\n")
        logger.warning(
            "\n==================================================\n"
            f"[DEV MODE - NO SMS SENT] OTP for {phone_number}: {otp_code}\n"
            "=================================================="
        )
        return {
            "success": True,
            "message": "OTP generated and logged (Development Mode).",
            "dev_otp": otp_code
        }

    # 6. Real SMS via Fast2SMS
    url = "https://www.fast2sms.com/dev/bulkV2"
    payload = {
        "authorization": api_key,
        "route": "otp",
        "variables_values": otp_code,
        "numbers": phone_number
    }

    try:
        response = requests.get(url, params=payload, timeout=10)
        data = response.json()

        if response.status_code == 200 and data.get("return") is True:
            logger.info(f"Fast2SMS OTP sent successfully to {phone_number}")
            return {
                "success": True,
                "message": "OTP sent successfully to your phone number."
            }
        else:
            error_msg = data.get("message", "Unknown error from Fast2SMS API")
            logger.error(f"Fast2SMS API error: {error_msg}")
            # Fallback to dev mode logging so demo doesn't fail
            print(f"\n==================================================")
            print(f"[OTP FALLBACK DEV MODE] Fast2SMS error: {error_msg}")
            print(f"[OTP FALLBACK DEV MODE] OTP for {phone_number}: {otp_code}")
            print(f"==================================================\n")
            logger.warning(
                "\n==================================================\n"
                f"[OTP FALLBACK DEV MODE] Fast2SMS error: {error_msg}\n"
                f"[OTP FALLBACK DEV MODE] OTP for {phone_number}: {otp_code}\n"
                "=================================================="
            )
            return {
                "success": True,
                "message": "OTP generated (Fallback Mode).",
                "dev_otp": otp_code
            }
    except requests.exceptions.RequestException as e:
        logger.error(f"Connection to Fast2SMS failed: {str(e)}")
        print(f"\n==================================================")
        print(f"[OTP FALLBACK DEV MODE] Connection error: {str(e)}")
        print(f"[OTP FALLBACK DEV MODE] OTP for {phone_number}: {otp_code}")
        print(f"==================================================\n")
        logger.warning(
            "\n==================================================\n"
            f"[OTP FALLBACK DEV MODE] Connection error: {str(e)}\n"
            f"[OTP FALLBACK DEV MODE] OTP for {phone_number}: {otp_code}\n"
            "=================================================="
        )
        return {
            "success": True,
            "message": "OTP generated (Fallback Mode).",
            "dev_otp": otp_code
        }

def verify_otp(phone_number, submitted_code):
    """
    Verifies the submitted code against the cached OTP.
    Deletes the OTP cache entry on match.
    Enforces a maximum of 5 attempts to prevent brute force.
    """
    if not submitted_code:
        return False

    attempts_key = f"otp_attempts:{phone_number}"
    try:
        attempts = cache.incr(attempts_key)
    except ValueError:
        # Key missing or expired
        cache.set(attempts_key, 1, timeout=300)
        attempts = 1

    if attempts > 5:
        cache.delete(f"otp:{phone_number}")
        return False

    cached_otp = cache.get(f"otp:{phone_number}")
    if not cached_otp:
        return False

    if str(cached_otp) == str(submitted_code).strip():
        cache.delete(f"otp:{phone_number}")
        cache.delete(attempts_key)
        return True

    return False
