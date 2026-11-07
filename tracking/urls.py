from django.urls import path

from .views import CollectView, ConsentView

urlpatterns = [path('track/', CollectView.as_view()), path('track/consent/', ConsentView.as_view())]
