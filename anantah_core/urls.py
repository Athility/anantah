from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.urls import re_path
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
]

# Serve media files:
# For local development and local Windows PC behind Cloudflare Tunnel (when Cloudinary is not configured),
# serve media files directly so product images and refined photos stream to the Vercel frontend.
if not getattr(settings, 'CLOUDINARY_CONFIGURED', False):
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
elif settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
