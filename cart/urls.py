from django.urls import path
from .views import (
    CartListView,
    CartAddView,
    CartItemDetailView,
    AddressListCreateView,
    CheckoutSummaryView,
    OrderCreateView,
    OrderListView,
)

# Cart routes: /api/cart/
cart_urlpatterns = [
    path('', CartListView.as_view(), name='cart-list'),
    path('add/', CartAddView.as_view(), name='cart-add'),
    path('<int:item_id>/', CartItemDetailView.as_view(), name='cart-item-detail'),
    path('addresses/', AddressListCreateView.as_view(), name='cart-addresses'),
]

# Order routes: /api/orders/
order_urlpatterns = [
    path('', OrderListView.as_view(), name='order-list'),
    path('checkout-summary/', CheckoutSummaryView.as_view(), name='checkout-summary'),
    path('create/', OrderCreateView.as_view(), name='order-create'),
]
