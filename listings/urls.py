from django.urls import path
from .views import ProductUploadView, VoiceCatalogView, ConfirmCatalogView, ProductDeleteView

urlpatterns = [
    path('upload/', ProductUploadView.as_view(), name='product_upload'),
    path('<int:product_id>/voice-catalog/', VoiceCatalogView.as_view(), name='voice_catalog'),
    path('<int:product_id>/confirm-catalog/', ConfirmCatalogView.as_view(), name='confirm_catalog'),
    path('<int:product_id>/delete/', ProductDeleteView.as_view(), name='product_delete'),
]
