from django.urls import path
from .views import (
    ProductUploadView,
    VoiceCatalogView,
    ConfirmCatalogView,
    ProductDeleteView,
    ArtisanAnalyticsView,
    IncrementProductViewView,
    ProductPauseView,
    VoiceTranscriptionView,
)

urlpatterns = [
    path('upload/', ProductUploadView.as_view(), name='product_upload'),
    path('transcribe/', VoiceTranscriptionView.as_view(), name='voice_transcription'),
    path('<int:product_id>/pause/', ProductPauseView.as_view(), name='product_pause'),
    path('<int:product_id>/voice-catalog/', VoiceCatalogView.as_view(), name='voice_catalog'),
    path('<int:product_id>/confirm-catalog/', ConfirmCatalogView.as_view(), name='confirm_catalog'),
    path('<int:product_id>/update/', ConfirmCatalogView.as_view(), name='product_update'),
    path('<int:product_id>/delete/', ProductDeleteView.as_view(), name='product_delete'),
    # Analytics — artisan-only, authenticated
    path('analytics/', ArtisanAnalyticsView.as_view(), name='artisan_analytics'),
    # View counter — public, atomic F() increment
    path('<int:product_id>/view/', IncrementProductViewView.as_view(), name='product_view_increment'),
]
