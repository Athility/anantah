import hmac
import hashlib
import razorpay
from django.conf import settings

def get_razorpay_client():
    """
    Returns an authenticated razorpay.Client.
    """
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise ValueError("Razorpay keys are not configured in settings.")
    try:
        return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    except Exception as e:
        raise Exception(f"Failed to initialize Razorpay Client: {str(e)}")

def create_razorpay_order(amount_rupees, receipt_id) -> dict:
    """
    Converts amount to paise as an int and creates a Razorpay order.
    """
    client = get_razorpay_client()
    try:
        # Convert amount in rupees to paise as an integer
        amount_paise = int(round(float(amount_rupees) * 100))
        data = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "payment_capture": 1
        }
        order_response = client.order.create(data=data)
        if not order_response or 'id' not in order_response:
            raise Exception("Invalid order response returned by Razorpay API.")
        return order_response
    except Exception as e:
        raise Exception(f"Razorpay order creation failed: {str(e)}")

def verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature) -> bool:
    """
    Verifies the payment signature using Razorpay's utility.
    Returns True if valid, False otherwise. Never raises an exception.
    """
    try:
        client = get_razorpay_client()
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        client.utility.verify_payment_signature(params_dict)
        return True
    except Exception:
        # Gracefully handle any signature verification error or API failure
        return False

def verify_webhook_signature(request_body: bytes, received_signature: str) -> bool:
    """
    Independently verifies Razorpay's webhook signature using RAZORPAY_WEBHOOK_SECRET and HMAC-SHA256.
    Returns True if valid, False otherwise. Never raises an exception.
    """
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret:
        return False
    try:
        # Compute signature using HMAC SHA256
        expected_signature = hmac.new(
            key=webhook_secret.encode('utf-8'),
            msg=request_body,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        # Prevent timing attacks
        return hmac.compare_digest(expected_signature, received_signature)
    except Exception:
        return False
