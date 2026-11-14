"""Public newsletter sign-up and membership plans (GAPS G-04, G-05)."""
from decimal import Decimal

from rest_framework.test import APIClient

from core.testing import TenantTestCase

from .models import MembershipBenefit, MembershipPlan, NewsletterSubscription

NEWSLETTER = '/api/v1/newsletter/'


class NewsletterTests(TenantTestCase):

    def test_sign_up_needs_consent_and_a_valid_email(self):
        self.assertIn('consent', APIClient().post(NEWSLETTER, {'email': 'a@example.com', 'consent': False}, format='json').data)
        self.assertIn('email', APIClient().post(NEWSLETTER, {'email': 'not-an-email', 'consent': True}, format='json').data)

    def test_sign_up_is_stored_once_and_case_insensitively(self):
        for email in ('Asha@Example.com', 'asha@example.com'):
            res = APIClient().post(NEWSLETTER, {'email': email, 'consent': True}, format='json')
            self.assertEqual((res.status_code, res.data['status']), (201, 'subscribed'))
        self.assertEqual(list(NewsletterSubscription.objects.values_list('email', flat=True)), ['asha@example.com'])

    def test_signing_up_again_after_unsubscribing_resubscribes(self):
        from django.utils import timezone
        NewsletterSubscription.objects.create(email='b@example.com', consent_at=timezone.now(), unsubscribed_at=timezone.now())
        APIClient().post(NEWSLETTER, {'email': 'b@example.com', 'consent': True}, format='json')
        self.assertIsNone(NewsletterSubscription.objects.get(email='b@example.com').unsubscribed_at)


class MembershipPlanTests(TenantTestCase):

    def test_only_active_plans_are_listed_cheapest_first_with_benefits(self):
        gold = MembershipPlan.objects.create(name='Gold', price=Decimal('4999'), duration_days=365, discount_basis_points=1500)
        MembershipBenefit.objects.create(plan=gold, text='15% off every trip')
        MembershipPlan.objects.create(name='Silver', price=Decimal('1999'), duration_days=180)
        MembershipPlan.objects.create(name='Retired', price=Decimal('99'), duration_days=30, is_active=False)
        res = APIClient().get('/api/v1/membership-plans/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual([p['name'] for p in res.data], ['Silver', 'Gold'])
        self.assertEqual((res.data[1]['discount_percent'], res.data[1]['benefits']), (15.0, ['15% off every trip']))
