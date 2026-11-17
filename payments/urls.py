from django.urls import path

from .views import CreateOrderView, VerifyView, cashfree_webhook

urlpatterns = [
    path('payments/cashfree/create-order/', CreateOrderView.as_view(), name='cashfree-create-order'),
    path('payments/cashfree/verify/<str:order_id>/', VerifyView.as_view(), name='cashfree-verify'),
    path('payments/cashfree/webhook/', cashfree_webhook, name='cashfree-webhook'),
]
