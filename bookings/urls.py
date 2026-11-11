from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('checkouts', views.CheckoutViewSet, basename='checkout')
router.register('bookings', views.BookingViewSet, basename='booking')
urlpatterns = [
    path('cart/', views.CartView.as_view(), name='cart'),
    path('coupons/preview/', views.CouponPreviewView.as_view(), name='coupon-preview'),
    path('safety-waivers/active/', views.ActiveSafetyWaiverView.as_view(), name='active-safety-waiver'),
] + router.urls
