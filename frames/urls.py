from django.urls import path
from .views import (
    FrameUploadView,
    FrameFeedView,
    FrameViewCountView,
    FrameLikeToggleView,
    FrameMineView,
    FrameStatsView,
)

urlpatterns = [
    path('upload/', FrameUploadView.as_view(), name='frame-upload'),
    path('feed/', FrameFeedView.as_view(), name='frame-feed'),
    path('<int:reel_id>/view/', FrameViewCountView.as_view(), name='frame-view-count'),
    path('<int:reel_id>/like/', FrameLikeToggleView.as_view(), name='frame-like-toggle'),
    path('mine/', FrameMineView.as_view(), name='frame-mine'),
    path('<int:reel_id>/stats/', FrameStatsView.as_view(), name='frame-stats'),
]
