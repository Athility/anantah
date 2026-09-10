import os
import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_verified_page(product, force_regenerate=False):
    """
    Generates a static, standalone Certificate of Authenticity HTML page for a product
    upon payment confirmation. Saves the file to verified_links/product_<product.id>.html.
    
    Loads artisan details from Aiven database and image URLs directly from Cloudinary.
    
    Idempotent: If the verified page for this product already exists and force_regenerate=False,
    generation is skipped.
    """
    if not product or not product.id:
        logger.warning("generate_verified_page called with invalid product instance.")
        return None

    # Target file path: verified_links/product_<product.id>.html
    target_dir = getattr(settings, 'VERIFIED_LINKS_DIR', os.path.join(settings.BASE_DIR, 'verified_links'))
    os.makedirs(target_dir, exist_ok=True)
    file_name = f"product_{product.id}.html"
    file_path = os.path.join(target_dir, file_name)

    # 1. Skip if page already exists unless force_regenerate is True
    if os.path.exists(file_path) and not force_regenerate:
        logger.info(f"Verified authenticity page already exists for product #{product.id} at {file_path}. Skipping.")
        return file_path

    try:
        # 2. Extract Artisan & Product Details from Aiven database
        artisan_name = "Master Artisan"
        artisan_region = ""
        craft_type = "Traditional Handicraft"
        
        if product.artisan:
            if hasattr(product.artisan, 'user') and product.artisan.user:
                u = product.artisan.user
                full_name = f"{u.first_name} {u.last_name}".strip()
                if not full_name:
                    raw_user = (u.username or "").strip()
                    # Clean up usernames like "jainil_artist" -> "Jainil Artist", "ayush" -> "Ayush"
                    full_name = raw_user.replace('_', ' ').replace('-', ' ').title()
                artisan_name = full_name if full_name else "Master Artisan"
                artisan_region = getattr(u, 'region', '')
                
            if hasattr(product.artisan, 'craft_type') and product.artisan.craft_type:
                craft_type = product.artisan.craft_type.title()
            elif product.category and product.category.name:
                craft_type = product.category.name.title()

        # 3. Resolve Image URL directly from Cloudinary
        image_url = ""
        cloud_name = getattr(settings, 'CLOUDINARY_CLOUD_NAME', '').strip() or 'q4xw3e2i'
        
        target_field = product.refined_image if product.refined_image else product.raw_image
        if target_field:
            try:
                raw_url = target_field.url
            except Exception:
                raw_url = ""

            field_name = str(target_field.name or '').strip()

            # If FieldFile gives an absolute Cloudinary / HTTPS URL
            if raw_url and raw_url.startswith(('http://', 'https://')):
                image_url = raw_url
            elif cloud_name and field_name:
                # Direct Cloudinary CDN construction
                clean_path = field_name.lstrip('/')
                image_url = f"https://res.cloudinary.com/{cloud_name}/image/upload/{clean_path}"
            elif field_name:
                base_url = getattr(settings, 'SITE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
                clean_path = field_name if field_name.startswith('/') else f"/{field_name}"
                image_url = f"{base_url}{clean_path}"

        # 4. Reference Number, Verification Date & Canonical URL
        base_url = getattr(settings, 'SITE_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        cert_ref_num = f"AN-AUTH-{product.id:06d}"
        verified_date = timezone.now().strftime("%B %d, %Y")
        canonical_url = f"{base_url}/verified_links/{file_name}"
        logo_url = f"{base_url}/anantah_logo.png"

        context = {
            'product': product,
            'artisan_name': artisan_name,
            'artisan_region': artisan_region,
            'craft_type': craft_type,
            'image_url': image_url or logo_url,
            'logo_url': logo_url,
            'cert_ref_num': cert_ref_num,
            'verified_date': verified_date,
            'canonical_url': canonical_url,
            'base_url': base_url,
        }

        # 5. Render HTML string via Django template engine
        html_content = render_to_string('verified_certificate.html', context)

        # 6. Write to verified_links/product_<id>.html
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Successfully generated verified authenticity certificate: {file_path} (Canonical: {canonical_url}, Artisan: {artisan_name}, Image: {image_url})")
        return file_path

    except Exception as e:
        logger.error(f"Failed to generate verified authenticity page for product #{product.id}: {str(e)}", exc_info=True)
        return None
