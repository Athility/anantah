from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import SignupSerializer, UserSerializer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from .otp_service import generate_and_send_otp, verify_otp

User = get_user_model()

class SendOTPView(APIView):
    permission_classes = [AllowAny]

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
            return Response({'success': True, 'message': 'Phone number verified successfully.'}, status=status.HTTP_200_OK)
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
