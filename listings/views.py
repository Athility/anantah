import os
from rest_framework import status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.files.base import ContentFile
from .models import Product
from .serializers import ProductSerializer
from ai_services.refiner import refine_image
from ai_services.voice_cataloger import (
    transcribe_and_translate,
    generate_catalog_entry,
)


class ProductUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user
        if user.role == 'artisan':
            # Artisans see all their own products
            try:
                artisan_profile = user.artisan_profile
                products = Product.objects.filter(artisan=artisan_profile).order_by('-created_at')
            except Exception:
                products = Product.objects.none()
        else:
            # Buyers and admins see all live products
            products = Product.objects.filter(status='live').order_by('-created_at')

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
            price_val = float(price)
        except ValueError:
            return Response(
                {"price": ["Must be a valid decimal number."]},
                status=status.HTTP_400_BAD_REQUEST
            )

        from PIL import Image
        try:
            with Image.open(raw_image) as img:
                img.verify()
            raw_image.seek(0)
        except Exception:
            return Response({'raw_image': ['Upload a valid image.']}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.exceptions import ValidationError
        product = Product(
            artisan=artisan_profile,
            title_en=title_en,
            price=price_val,
            raw_image=raw_image,
            status='live'
        )
        try:
            product.full_clean(exclude=['title_hi', 'description_en', 'description_hi', 'category_en', 'category_hi', 'audio_description_hi'])
        except ValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)
        
        product.save()

        # Parse selected enhancements (comma-separated string from form-data)
        enhancements_raw = request.data.get('enhancements', '')
        enhancements = [e.strip() for e in enhancements_raw.split(',') if e.strip()]

        # 2. Perform AI Image refinement with only selected tools
        try:
            refined_io = refine_image(product.raw_image.file, enhancements=enhancements)

            raw_name = os.path.basename(product.raw_image.name)
            refined_name = f"refined_{raw_name}"

            if not refined_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                base, _ = os.path.splitext(refined_name)
                refined_name = f"{base}.jpg"

            product.refined_image.save(
                refined_name,
                ContentFile(refined_io.read()),
                save=True
            )
        except Exception as e:
            product.delete()
            return Response(
                {"detail": f"AI Image refinement failed: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        serializer = ProductSerializer(product, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class VoiceCatalogView(APIView):
    """
    POST /api/listings/<product_id>/voice-catalog/

    Accepts a voice note audio file. Runs the full Groq Whisper → HF fallback
    → Groq LLaMA pipeline synchronously and returns staged results for the
    artisan to review before publishing.

    The audio file is always saved to products.raw_audio before any processing
    begins, so the artisan never loses their recording if the pipeline fails.

    Request (multipart/form-data):
        audio_file – required, audio file (.webm, .wav, .mp3, .m4a, .ogg, .flac)

    Response 200 (pipeline succeeded):
        {
          "transcript_en":  "<English transcript from Groq/HF Whisper>",
          "title_en":       "<generated English title>",
          "title_hi":       "<generated Hindi title>",
          "description_en": "<generated English description>",
          "description_hi": "<generated Hindi description>"
        }

    Response 422 (pipeline stage error, audio still saved):
        { "stage": "transcription"|"generation", "detail": "<user-friendly message>" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, product_id, *args, **kwargs):
        user = request.user

        # --- Auth checks ---
        if user.role != 'artisan':
            return Response(
                {"detail": "Only artisans can use the voice cataloger."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            artisan_profile = user.artisan_profile
        except Exception:
            return Response(
                {"detail": "Artisan profile not found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Product ownership check ---
        try:
            product = Product.objects.get(pk=product_id, artisan=artisan_profile)
        except Product.DoesNotExist:
            return Response(
                {"detail": "Product not found or does not belong to you."},
                status=status.HTTP_404_NOT_FOUND
            )

        # --- Input validation ---
        audio_file = request.FILES.get('audio_file')
        if not audio_file:
            return Response(
                {"detail": "audio_file is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        source_language = request.data.get('source_language', 'hi').strip().lower()

        # --- Always save raw audio first (before pipeline runs) ---
        # This ensures the artisan's audio is preserved even if processing fails.
        audio_file.seek(0)
        product.raw_audio.save(
            f"voice_{product_id}_{audio_file.name}",
            ContentFile(audio_file.read()),
            save=True
        )

        # --- STAGE 1: Transcription + Translation (Groq Whisper → HF fallback) ---
        try:
            # Re-open from the saved file to ensure a clean stream for the API
            with product.raw_audio.open('rb') as saved_audio:
                saved_audio.name = audio_file.name  # Preserve extension for MIME detection
                transcript_en = transcribe_and_translate(saved_audio)
        except RuntimeError as e:
            return Response(
                {
                    "stage":  "transcription",
                    "detail": str(e),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        except Exception as e:
            return Response(
                {
                    "stage":  "transcription",
                    "detail": f"Transcription failed unexpectedly: {str(e)}",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        # --- STAGE 2: Bilingual SEO Description Generation (Groq LLaMA) ---
        category_name = product.category.name if product.category else ''
        try:
            catalog = generate_catalog_entry(
                english_transcript=transcript_en,
                category_name=category_name,
                existing_title_en=product.title_en or '',
                source_language=source_language,
            )
        except RuntimeError as e:
            return Response(
                {
                    "stage":  "generation",
                    "detail": str(e),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )
        except Exception as e:
            return Response(
                {
                    "stage":  "generation",
                    "detail": f"Description generation failed unexpectedly: {str(e)}",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

        # --- Return staged results for artisan review (not written to DB yet) ---
        return Response({
            "transcript_en":  transcript_en,
            "title_en":       catalog.get('title_en', ''),
            "title_hi":       catalog.get('title_hi', ''),
            "description_en": catalog.get('description_en', ''),
            "description_hi": catalog.get('description_hi', ''),
        }, status=status.HTTP_200_OK)


class ConfirmCatalogView(APIView):
    """
    PATCH /api/listings/<product_id>/confirm-catalog/

    Saves the artisan's (possibly edited) catalog fields to the product
    and sets its status to 'live'. This is the only endpoint that writes
    title/description to the database — the artisan must explicitly confirm.

    Request (JSON):
        {
          "title_en":       "...",  (optional — skipped if blank)
          "title_hi":       "...",  (optional)
          "description_en": "...",  (optional)
          "description_hi": "..."   (optional)
        }

    Response 200:
        Full ProductSerializer representation of the updated (live) product.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, product_id, *args, **kwargs):
        user = request.user

        if user.role != 'artisan':
            return Response(
                {"detail": "Only artisans can confirm catalog entries."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            artisan_profile = user.artisan_profile
        except Exception:
            return Response(
                {"detail": "Artisan profile not found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            product = Product.objects.get(pk=product_id, artisan=artisan_profile)
        except Product.DoesNotExist:
            return Response(
                {"detail": "Product not found or does not belong to you."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Update fields that were actually provided and non-empty
        for field in ('title_en', 'title_hi', 'description_en', 'description_hi'):
            value = request.data.get(field, '').strip()
            if value:
                setattr(product, field, value)

        # Publish the product
        product.status = 'live'
        product.save()

        serializer = ProductSerializer(product, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProductDeleteView(APIView):
    """
    DELETE /api/listings/<product_id>/delete/

    Permanently deletes a product listing that belongs to the authenticated artisan.
    Both live and draft products can be deleted.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, product_id, *args, **kwargs):
        user = request.user

        if user.role != 'artisan':
            return Response(
                {"detail": "Only artisans can delete their listings."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            artisan_profile = user.artisan_profile
        except Exception:
            return Response(
                {"detail": "Artisan profile not found."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            product = Product.objects.get(pk=product_id, artisan=artisan_profile)
        except Product.DoesNotExist:
            return Response(
                {"detail": "Product not found or does not belong to you."},
                status=status.HTTP_404_NOT_FOUND
            )

        product.delete()
        return Response({"detail": "Listing deleted successfully."}, status=status.HTTP_200_OK)
