from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('checkouts', views.CheckoutViewSet, basename='checkout')
router.register('bookings', views.BookingViewSet, basename='booking')
urlpatterns = [path('cart/', views.CartView.as_view(), name='cart')] + router.urls
