from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('destinations', views.DestinationViewSet, basename='destination')
router.register('blogs', views.BlogViewSet, basename='blog')
router.register('pages', views.CmsPageViewSet, basename='page')
router.register('faqs', views.FAQViewSet, basename='faq')
router.register('testimonials', views.TestimonialViewSet, basename='testimonial')
urlpatterns = [path('site-settings/', views.SiteSettingsView.as_view(), name='site-settings')] + router.urls
