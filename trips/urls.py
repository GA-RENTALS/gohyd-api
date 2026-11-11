from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('trips', views.TripViewSet, basename='trip')
router.register('events', views.EventViewSet, basename='event')
router.register('categories', views.TripCategoryViewSet, basename='category')
urlpatterns = router.urls
