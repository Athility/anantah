import os
import re
import logging
from rest_framework import status, permissions
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.response import Response
from django.core.files.base import ContentFile
from django.db.models import Q
from rapidfuzz import fuzz
from .models import Product
from .serializers import ProductSerializer
from ai_services.refiner import refine_image
from ai_services.voice_cataloger import (
    transcribe_and_translate,
    generate_catalog_entry,
)

logger = logging.getLogger(__name__)

STOPWORDS = {
    'a', 'an', 'the', 'for', 'in', 'on', 'of', 'and', 'or', 'to',
    'with', 'at', 'by', 'from', 'is', 'it', 'as', 'into', 'about'
}


def perform_product_search(query_str, base_queryset=None, threshold=72.0, min_exact_count=3, max_candidates=500):
    """
    Two-stage typo-tolerant product search:
    Stage 1: Fast exact / icontains database filter across title, description, category, and artisan name.
    Stage 2: If fewer than `min_exact_count` matches, run a rapidfuzz fuzzy fallback over up to `max_candidates`
             live products, scoring multi-word queries with stopword filtering.
    """
    if base_queryset is None:
        base_queryset = Product.objects.filter(status='live')

    query = (query_str or '').strip()
    if not query:
        return base_queryset.order_by('-created_at')

    # Stage 1: Fast Substring / icontains search
    exact_q = (
        Q(title_en__icontains=query) |
        Q(title_hi__icontains=query) |
        Q(description_en__icontains=query) |
        Q(description_hi__icontains=query) |
        Q(category__name__icontains=query) |
        Q(artisan__user__first_name__icontains=query) |
        Q(artisan__user__last_name__icontains=query) |
        Q(artisan__user__username__icontains=query)
    )
    exact_matches = list(
        base_queryset.filter(exact_q)
        .select_related('category', 'artisan__user')
        .order_by('-created_at')
    )

    # If exact pass found enough results, return immediately (fast path)
    if len(exact_matches) >= min_exact_count:
        logger.info(
            "[Search] Exact match for '%s' returned %d results; skipping fuzzy fallback.",
            query, len(exact_matches)
        )
        return exact_matches

    # Stage 2: Typo-tolerant fuzzy fallback
    logger.info(
        "[Search] Exact match for '%s' returned %d (< %d) results; triggering fuzzy fallback.",
        query, len(exact_matches), min_exact_count
    )

    exact_ids = {p.id for p in exact_matches}

    # Fetch candidate pool (capped for performance)
    candidates = list(
        base_queryset.exclude(id__in=exact_ids)
        .select_related('category', 'artisan__user')
        .order_by('-created_at')[:max_candidates]
    )

    # Multi-word tokenization and stopword removal
    raw_tokens = [w.lower() for w in re.findall(r'[\w]+', query) if w]
    sig_words = [w for w in raw_tokens if w not in STOPWORDS and len(w) >= 2]
    if not sig_words:
        sig_words = raw_tokens if raw_tokens else [query.lower()]

    fuzzy_scored_products = []

    for product in candidates:
        t_en = (product.title_en or '').lower()
        t_hi = (product.title_hi or '').lower()
        cat = (product.category.name if product.category else '').lower()
        d_en = (product.description_en or '').lower()

        artisan_user = product.artisan.user if (product.artisan and getattr(product.artisan, 'user', None)) else None
        artisan_name = (
            f"{artisan_user.first_name} {artisan_user.last_name}".strip()
            if artisan_user else ''
        ).lower()

        full_text = f"{t_en} {t_hi} {cat} {artisan_name} {d_en}"
        doc_tokens = [t for t in re.findall(r'[\w]+', full_text) if len(t) >= 2]
        fields = [t_en, t_hi, cat, artisan_name, d_en]

        # Multi-word scoring
        word_scores = []
        for word in sig_words:
            if any(word in f for f in fields if f):
                word_scores.append(100.0)
                continue

            token_ratios = [fuzz.ratio(word, dt) for dt in doc_tokens] if doc_tokens else [0.0]
            max_token_ratio = max(token_ratios) if token_ratios else 0.0

            field_partials = [fuzz.partial_ratio(word, f) for f in fields if f]
            max_field_partial = max(field_partials) if field_partials else 0.0

            best_word_score = max(max_token_ratio, max_field_partial)
            word_scores.append(best_word_score)

        if not word_scores:
            continue

        avg_score = sum(word_scores) / len(word_scores)

        phrase_score = max(
            fuzz.partial_ratio(query.lower(), full_text),
            fuzz.token_set_ratio(query.lower(), full_text)
        )

        overall_score = max(avg_score, phrase_score)

        if overall_score >= threshold:
            fuzzy_scored_products.append((product, overall_score))

    # Sort fuzzy matches by similarity score descending (best matches first)
    fuzzy_scored_products.sort(key=lambda item: item[1], reverse=True)
    fuzzy_results = [p for p, _ in fuzzy_scored_products]

    logger.info(
        "[Search] Fuzzy fallback for '%s' completed. Found %d fuzzy matches.",
        query, len(fuzzy_results)
    )

    return exact_matches + fuzzy_results


class ProductUploadThrottle(ScopedRateThrottle):
    scope = 'product_upload'

    def allow_request(self, request, view):
        if request.method != 'POST':
            return True
        return super().allow_request(request, view)


class ProductUploadView(APIView):
    throttle_classes = [ProductUploadThrottle]

    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get(self, request, *args, **kwargs):
        user = request.user
        search_query = request.query_params.get('search') or request.query_params.get('q')

        if user.is_authenticated and getattr(user, 'role', None) == 'artisan':
            # Artisans see their own products
            try:
                artisan_profile = user.artisan_profile
                base_qs = Product.objects.filter(artisan=artisan_profile)
            except Exception:
                base_qs = Product.objects.none()

            if search_query:
                products = perform_product_search(search_query, base_queryset=base_qs)
            else:
                products = base_qs.order_by('-created_at')
        else:
            # Unauthenticated guests, buyers, and admins see all live products
            base_qs = Product.objects.filter(status='live')
            if search_query:
                products = perform_product_search(search_query, base_queryset=base_qs)
            else:
                products = base_qs.order_by('-created_at')

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
            if price_val < 0.01:
                return Response(
                    {"price": ["Price must be at least 0.01."]},
                    status=status.HTTP_400_BAD_REQUEST
                )
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
            status='draft'
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'voice_catalog'

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

        # BUG-8: 1. Size Validation (Limit to 5MB for voice notes)
        if audio_file.size > 5 * 1024 * 1024:
            return Response({"detail": "Audio file too large. Maximum size is 5MB."}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-8: 2. Extension Validation
        import os
        ext = os.path.splitext(audio_file.name)[1].lower()
        allowed_exts = {'.webm', '.wav', '.mp3', '.m4a', '.ogg', '.flac'}
        if ext not in allowed_exts:
            return Response({"detail": "Unsupported audio extension."}, status=status.HTTP_400_BAD_REQUEST)

        # BUG-8: 3. Content Validation (Magic bytes / signatures)
        # Avoid external dependencies by checking known audio container headers.
        audio_file.seek(0)
        header = audio_file.read(12)
        audio_file.seek(0)

        is_valid_audio = False
        if header.startswith(b'\x1a\x45\xdf\xa3'):
            is_valid_audio = True # WebM
        elif header.startswith(b'RIFF') and header[8:12] == b'WAVE':
            is_valid_audio = True # WAV
        elif header.startswith(b'ID3') or (len(header) >= 2 and header[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')):
            is_valid_audio = True # MP3
        elif len(header) >= 8 and header[4:8] == b'ftyp':
            is_valid_audio = True # MP4/M4A variants
        elif header.startswith(b'OggS'):
            is_valid_audio = True # OGG
        elif header.startswith(b'fLaC'):
            is_valid_audio = True # FLAC
            
        if not is_valid_audio:
            return Response({"detail": "File content does not match a supported audio format."}, status=status.HTTP_400_BAD_REQUEST)

        source_language = request.data.get('source_language', 'hi').strip().lower()

        old_audio_name = product.raw_audio.name if product.raw_audio else None

        # --- Always save raw audio first (before pipeline runs) ---
        # This ensures the artisan's audio is preserved even if processing fails.
        audio_file.seek(0)
        audio_bytes = audio_file.read()
        product.raw_audio.save(
            f"voice_{product_id}_{audio_file.name}",
            ContentFile(audio_bytes),
            save=True
        )

        # BUG-7: Delete the previous orphaned audio file securely from storage
        if old_audio_name and old_audio_name != product.raw_audio.name:
            try:
                product.raw_audio.storage.delete(old_audio_name)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to cleanup old audio {old_audio_name}: {e}")

        # --- STAGE 1: Transcription + Translation (Groq Whisper → HF fallback) ---
        try:
            import io
            audio_stream = io.BytesIO(audio_bytes)
            audio_stream.name = audio_file.name  # Preserve extension for MIME detection
            transcript_en = transcribe_and_translate(audio_stream)
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
        from django.core.exceptions import ValidationError
        
        for field in ('title_en', 'title_hi', 'description_en', 'description_hi'):
            value = request.data.get(field)
            if value is not None:
                value = str(value).strip()
                
                # Explicit bounds to prevent SQLite massive payload DoS
                if field in ('title_en', 'title_hi') and len(value) > 200:
                    return Response({'detail': f'{field} exceeds maximum length of 200 characters.'}, status=status.HTTP_400_BAD_REQUEST)
                if field in ('description_en', 'description_hi') and len(value) > 10000:
                    return Response({'detail': f'{field} exceeds maximum length.'}, status=status.HTTP_400_BAD_REQUEST)
                
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
