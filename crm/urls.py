from django.urls import path

from .views import CorporateEnquiryView, EnquiryView

urlpatterns = [path('enquiries/', EnquiryView.as_view()), path('corporate-enquiries/', CorporateEnquiryView.as_view())]
