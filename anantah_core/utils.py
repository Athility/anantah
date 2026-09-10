import os
from django.conf import settings


def build_public_media_url(file_field_or_url, request=None):
    """
    Builds a public, deployment-safe media URL for product images and audio.
    
    1. If Cloudinary or an external CDN is used (starts with http/https), return as-is.
    2. If PUBLIC_API_URL is configured (e.g. Cloudflare Tunnel hostname or custom domain),
       use it to form the absolute URL instead of localhost.
    3. If request is available:
       Use request.build_absolute_uri() which respects USE_X_FORWARDED_HOST and
       SECURE_PROXY_SSL_HEADER. If request produces a localhost URL but PUBLIC_API_URL is set,
       rewrite localhost to PUBLIC_API_URL.
    4. Fallback: request.build_absolute_uri() or relative URL.
    """
    if not file_field_or_url:
        return None

    # If passed a FieldFile (like obj.raw_image), get .url
    if hasattr(file_field_or_url, 'url'):
        try:
            url = file_field_or_url.url
        except (ValueError, AttributeError):
            return None
    else:
        url = str(file_field_or_url).strip()

    if not url:
        return None

    public_api = getattr(settings, 'PUBLIC_API_URL', '').rstrip('/')

    # Already absolute remote URL (e.g., Cloudinary CDN, data, blob)
    if url.startswith(('http://', 'https://', 'data:', 'blob:')):
        # If it's a localhost URL and PUBLIC_API_URL is configured, rewrite it
        if public_api and (url.startswith('http://127.0.0.1:8000') or url.startswith('http://localhost:8000')):
            rel = url.replace('http://127.0.0.1:8000', '').replace('http://localhost:8000', '')
            return f"{public_api}{rel}"
        return url

    # It is a relative path (e.g., '/media/products/refined/xxx.jpg' or 'products/...')
    if not url.startswith('/'):
        url = f"/{url}"

    if public_api:
        return f"{public_api}{url}"

    if request:
        abs_uri = request.build_absolute_uri(url)
        return abs_uri

    return url
