from django.urls import path
from .views import CreateRazorpayOrderView, VerifyPaymentView, RazorpayWebhookView

urlpatterns = [
    path('create-order/', CreateRazorpayOrderView.as_view(), name='create-razorpay-order'),
    path('verify/', VerifyPaymentView.as_view(), name='verify-payment'),
    path('webhook/', RazorpayWebhookView.as_view(), name='razorpay-webhook'),
]
