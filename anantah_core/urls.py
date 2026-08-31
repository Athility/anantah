from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from cart.urls import cart_urlpatterns, order_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),
    path('api/listings/', include('listings.urls')),
    path('api/cart/', include(cart_urlpatterns)),
    path('api/orders/', include(order_urlpatterns)),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
