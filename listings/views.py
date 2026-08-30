import os
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.files.base import ContentFile
from .models import Product
from .serializers import ProductSerializer
from ai_services.refiner import refine_image

class ProductUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        if user.role == 'artisan':
            # Artisans see only their own products
            try:
                artisan_profile = user.artisan_profile
                products = Product.objects.filter(artisan=artisan_profile).order_by('-created_at')
            except Exception:
                products = Product.objects.none()
        else:
            # Buyers and admins see all products
            products = Product.objects.all().order_by('-created_at')
        
        serializer = ProductSerializer(products, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        user = request.user
        
        # Verify artisan role
        if user.role != 'artisan':
            return Response(
                {"detail": "Only artisans can upload and refine products."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        try:
            artisan_profile = user.artisan_profile
        except Exception:
            return Response(
                {"detail": "Artisan profile not found for this user."},
                status=status.HTTP_400_BAD_REQUEST
            )

        title_en = request.data.get('title_en')
        price = request.data.get('price')
        raw_image = request.FILES.get('raw_image')

        # Validation
        errors = {}
        if not title_en:
            errors['title_en'] = ["This field is required."]
        if not price:
            errors['price'] = ["This field is required."]
        if not raw_image:
            errors['raw_image'] = ["This field is required."]

        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Convert price to float/decimal
            price_val = float(price)
        except ValueError:
            return Response(
                {"price": ["Must be a valid decimal number."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Create and save product with raw image
        product = Product.objects.create(
            artisan=artisan_profile,
            title_en=title_en,
            price=price_val,
            raw_image=raw_image,
            status='live'  # Automatically set to live for hackathon demo
        )

        # 2. Perform AI Image refinement synchronously
        try:
            refined_io = refine_image(product.raw_image.file)
            
            # Generate a name for the refined image
            raw_name = os.path.basename(product.raw_image.name)
            refined_name = f"refined_{raw_name}"
            
            # Ensure it ends with an image extension
            if not refined_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                base, _ = os.path.splitext(refined_name)
                refined_name = f"{base}.jpg"
                
            # Save the refined file to the product
            product.refined_image.save(
                refined_name,
                ContentFile(refined_io.read()),
                save=True
            )
        except Exception as e:
            # If AI processing fails, log it and return the error
            # We can delete the created product draft to avoid orphaned files
            product.delete()
            return Response(
                {"detail": f"AI Image refinement failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        serializer = ProductSerializer(product, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
