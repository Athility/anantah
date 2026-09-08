import secrets
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import SignupSerializer, UserSerializer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from .otp_service import generate_and_send_otp, verify_otp
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

def revoke_all_user_tokens(user):
    tokens = OutstandingToken.objects.filter(user=user)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)

User = get_user_model()

class SendOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_request'

    def post(self, request, *args, **kwargs):
        phone = (request.data.get('phone') or '').strip()
        if not phone:
            return Response({'phone': ['Phone number is required.']}, status=status.HTTP_400_BAD_REQUEST)
            
        # Basic validation: ensure digits and reasonable length
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 15:
            return Response({'phone': ['Please enter a valid phone number.']}, status=status.HTTP_400_BAD_REQUEST)

        # Check if phone number is already taken
        if User.objects.filter(phone=phone).exists():
            return Response({'phone': ['A user with this phone number already exists.']}, status=status.HTTP_400_BAD_REQUEST)

        res = generate_and_send_otp(phone)
        if res['success']:
            return Response({'message': res['message']}, status=status.HTTP_200_OK)
        else:
            return Response({'non_field_errors': [res['message']]}, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_verify'

    def post(self, request, *args, **kwargs):
        phone = (request.data.get('phone') or '').strip()
        otp = (request.data.get('otp') or '').strip()

        if not phone or not otp:
            return Response({'non_field_errors': ['Phone and OTP are required.']}, status=status.HTTP_400_BAD_REQUEST)

        # Basic validation: ensure digits
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 15:
            return Response({'phone': ['Please enter a valid phone number.']}, status=status.HTTP_400_BAD_REQUEST)

        if verify_otp(phone, otp):
            # Set verification status in cache with 15 min TTL (900 seconds)
            cache.set(f"phone_verified:{phone}", True, timeout=900)
            reg_token = secrets.token_urlsafe(32)
            cache.set(f"reg_token:{reg_token}", phone, timeout=900)
            return Response({
                'success': True,
                'message': 'Phone number verified successfully.',
                'registration_token': reg_token
            }, status=status.HTTP_200_OK)
        else:
            return Response({'otp': ['Invalid or expired OTP. Please try again.']}, status=status.HTTP_400_BAD_REQUEST)


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PasswordResetSendOTPView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_request'

    def post(self, request, *args, **kwargs):
        identifier = (request.data.get('identifier') or request.data.get('phone') or '').strip()
        if not identifier:
            return Response({'identifier': ['Please provide your registered phone number or username.']}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(phone=identifier).first() or User.objects.filter(username=identifier).first()
        if not user or not user.phone:
            return Response({'identifier': ['No registered account found matching this identifier.']}, status=status.HTTP_404_NOT_FOUND)

        res = generate_and_send_otp(user.phone)
        if res['success']:
            return Response({'message': res['message'], 'phone': user.phone}, status=status.HTTP_200_OK)
        else:
            return Response({'non_field_errors': [res['message']]}, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otp_verify'

    def post(self, request, *args, **kwargs):
        phone = (request.data.get('phone') or '').strip()
        otp = (request.data.get('otp') or '').strip()
        new_password = (request.data.get('new_password') or '').strip()

        if not phone or not otp or not new_password:
            return Response({'non_field_errors': ['Phone, OTP, and new_password are required.']}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 4:
            return Response({'new_password': ['Password must be at least 4 characters long.']}, status=status.HTTP_400_BAD_REQUEST)

        if not verify_otp(phone, otp):
            return Response({'otp': ['Invalid or expired OTP. Please try again.']}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(phone=phone).first()
        if not user:
            return Response({'non_field_errors': ['User not found.']}, status=status.HTTP_404_NOT_FOUND)

        user.set_password(new_password)
        user.save()
        revoke_all_user_tokens(user)
        return Response({'success': True, 'message': 'Password reset successfully. You can now log in.'}, status=status.HTTP_200_OK)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({'detail': 'Refresh token is required.'}, status=status.HTTP_400_BAD_REQUEST)
            
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'detail': 'Invalid or expired token.'}, status=status.HTTP_400_BAD_REQUEST)

class DeleteAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        user = request.user
        with transaction.atomic():
            revoke_all_user_tokens(user)
            user.delete()
        return Response({'detail': 'Account deleted successfully.'}, status=status.HTTP_200_OK)


