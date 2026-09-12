from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from cart.urls import cart_urlpatterns, order_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/listings/', include('listings.urls')),
    path('api/cart/', include(cart_urlpatterns)),
    path('api/orders/', include(order_urlpatterns)),
    path('api/payments/', include('payments.urls')),
    path('api/wishlist/', include('wishlist.urls')),
    path('api/frames/', include('frames.urls')),
    
    # Static serving for auto-generated verified authenticity certificate HTML pages.
    # NOTE FOR PRODUCTION / VERCEL:
    # In serverless environments (such as Vercel) where the filesystem is read-only / ephemeral,
    # static pages generated at runtime should either be stored in persistent blob storage
    # (e.g. Cloudinary, AWS S3) or routed via static rewrites in vercel.json.
    # In local development and traditional persistent servers, this serves directly from verified_links/.
    path('verified_links/<path:path>', serve, {'document_root': getattr(settings, 'VERIFIED_LINKS_DIR', settings.BASE_DIR / 'verified_links')}),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

