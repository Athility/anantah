import os
import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

# Boilerplate URL for verified QR codes
VERIFIED_QR_BOILERPLATE = "http://10.213.106.90:8000/verified_links/"

# Hardcoded reference links for highest reliability
HARDCODED_VERIFIED_LINKS = {
    "product_61.html": "http://10.213.106.90:8000/verified_links/product_61.html",
    "product_62.html": "http://10.213.106.90:8000/verified_links/product_62.html",
    "product_63.html": "http://10.213.106.90:8000/verified_links/product_63.html",
}


def generate_verified_qr_for_file(html_filename, target_dir=None):
    """
    Generates a high-quality QR code image for a verified product HTML file.
    Appends html_filename to VERIFIED_QR_BOILERPLATE (or uses HARDCODED_VERIFIED_LINKS).
    Saves to verified_qr/<stem>.png (e.g., verified_qr/product_61.png).
    """
    try:
        import qrcode
    except ImportError:
        logger.error("qrcode library is not installed. Run 'pip install qrcode pillow'.")
        return None

    if target_dir is None:
        target_dir = getattr(settings, 'VERIFIED_QR_DIR', os.path.join(settings.BASE_DIR, 'verified_qr'))
    os.makedirs(target_dir, exist_ok=True)

    # Resolve target URL
    clean_html_filename = os.path.basename(html_filename)
    if clean_html_filename in HARDCODED_VERIFIED_LINKS:
        qr_url = HARDCODED_VERIFIED_LINKS[clean_html_filename]
    else:
        qr_url = f"{VERIFIED_QR_BOILERPLATE.rstrip('/')}/{clean_html_filename}"

    stem = os.path.splitext(clean_html_filename)[0]
    qr_file_path = os.path.join(target_dir, f"{stem}.png")

    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(qr_file_path)
        logger.info(f"Successfully generated verified QR: {qr_file_path} for target {qr_url}")
        return qr_file_path
    except Exception as e:
        logger.error(f"Error generating QR code for {clean_html_filename} ({qr_url}): {e}", exc_info=True)
        return None


def generate_all_verified_qrs(verified_links_dir=None, target_dir=None):
    """
    Iterates through all HTML files in verified_links/ and creates QR codes in verified_qr/.
    """
    if verified_links_dir is None:
        verified_links_dir = getattr(settings, 'VERIFIED_LINKS_DIR', os.path.join(settings.BASE_DIR, 'verified_links'))

    if not os.path.exists(verified_links_dir):
        logger.warning(f"Verified links directory not found at {verified_links_dir}")
        return []

    generated_files = []
    # 1. Process files present in verified_links folder
    for fname in os.listdir(verified_links_dir):
        if fname.endswith('.html'):
            qr_path = generate_verified_qr_for_file(fname, target_dir=target_dir)
            if qr_path:
                generated_files.append(qr_path)

    # 2. Ensure hardcoded products are generated
    for fname in HARDCODED_VERIFIED_LINKS.keys():
        if fname not in [os.path.basename(f) for f in os.listdir(verified_links_dir) if f.endswith('.html')]:
            qr_path = generate_verified_qr_for_file(fname, target_dir=target_dir)
            if qr_path:
                generated_files.append(qr_path)

    return generated_files


def generate_verified_page(product, force_regenerate=False):
    """
    Generates a static, standalone Certificate of Authenticity HTML page for a product
    upon payment confirmation or artisan listing. Saves the file to verified_links/product_<product.id>.html.
    Also automatically generates the corresponding QR code into verified_qr/product_<product.id>.png.
    
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

    # 1. Skip HTML generation if page already exists unless force_regenerate is True
    if os.path.exists(file_path) and not force_regenerate:
        logger.info(f"Verified authenticity page already exists for product #{product.id} at {file_path}. Skipping HTML rendering.")
        # Ensure QR exists
        generate_verified_qr_for_file(file_name)
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

        # 7. Automatically generate QR code into verified_qr/
        generate_verified_qr_for_file(file_name)

        logger.info(f"Successfully generated verified authenticity certificate: {file_path} (Canonical: {canonical_url}, Artisan: {artisan_name}, Image: {image_url})")
        return file_path

    except Exception as e:
        logger.error(f"Failed to generate verified authenticity page for product #{product.id}: {str(e)}", exc_info=True)
        return None

