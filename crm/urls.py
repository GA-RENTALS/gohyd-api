from django.urls import path

from .views import (CorporateEnquiryView, EnquiryView, MembershipPlanListView, NewsletterSubscribeView,
                    NewsletterUnsubscribeView)

urlpatterns = [
    path('enquiries/', EnquiryView.as_view()),
    path('corporate-enquiries/', CorporateEnquiryView.as_view()),
    path('newsletter/', NewsletterSubscribeView.as_view(), name='newsletter-subscribe'),
    path('newsletter/unsubscribe/', NewsletterUnsubscribeView.as_view(), name='newsletter-unsubscribe'),
    path('membership-plans/', MembershipPlanListView.as_view(), name='membership-plans'),
]
