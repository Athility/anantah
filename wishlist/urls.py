from django.urls import path
from .views import (
    WishlistAddView,
    WishlistListView,
    WishlistItemDeleteView,
    WishlistCheckView,
)

urlpatterns = [
    path('add/', WishlistAddView.as_view(), name='wishlist-add'),
    path('', WishlistListView.as_view(), name='wishlist-list'),
    path('<int:item_id>/', WishlistItemDeleteView.as_view(), name='wishlist-delete'),
    path('check/<int:product_id>/', WishlistCheckView.as_view(), name='wishlist-check'),
]
