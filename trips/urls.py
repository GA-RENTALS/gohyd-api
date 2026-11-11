from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('trips', views.TripViewSet, basename='trip')
router.register('events', views.EventViewSet, basename='event')
router.register('categories', views.TripCategoryViewSet, basename='category')
urlpatterns = [
    path('me/event-bookings/', views.MyEventBookingsView.as_view(), name='my-event-bookings'),
    path('event-bookings/', views.EventBookingCreateView.as_view(), name='event-booking-create'),
    path('event-bookings/<str:reference>/', views.EventBookingStatusView.as_view(), name='event-booking-status'),
    path('event-bookings/<str:reference>/payment-proof/', views.EventPaymentProofView.as_view(), name='event-booking-payment-proof'),
] + router.urls
