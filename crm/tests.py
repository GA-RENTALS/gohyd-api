from core.testing import TenantTestCase
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Enquiry


class EnquiryTests(TenantTestCase):
    def test_enquiry_requires_a_way_to_reply(self):
        self.assertEqual(APIClient().post('/api/v1/enquiries/', {'name': 'A'}, format='json').status_code, 400)

    def test_enquiry_saved_with_source(self):
        r = APIClient().post('/api/v1/enquiries/', {'name': 'A', 'phone': '9876543210', 'consent_to_contact': True}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Enquiry.objects.get().source.name, 'website')


class NewsletterUnsubscribeTests(TenantTestCase):
    """Each subscriber's signed link unsubscribes them, and only them (NEXT.md item 30)."""

    def setUp(self):
        from django.utils import timezone
        from .models import NewsletterSubscription
        self.sub = NewsletterSubscription.objects.create(email='reader@example.com', consent_at=timezone.now())
        self.other = NewsletterSubscription.objects.create(email='other@example.com', consent_at=timezone.now())

    def _post(self, token):
        return APIClient().post('/api/v1/newsletter/unsubscribe/', {'token': token}, format='json')

    def test_the_link_unsubscribes_that_address_once(self):
        from .newsletter import unsubscribe_token, unsubscribe_url
        self.assertIn('/newsletter/unsubscribe?token=', unsubscribe_url(self.sub))
        res = self._post(unsubscribe_token(self.sub))
        self.assertEqual((res.status_code, res.data['email']), (200, 'reader@example.com'))
        self.sub.refresh_from_db(); self.other.refresh_from_db()
        first = self.sub.unsubscribed_at
        self.assertIsNotNone(first)
        self.assertIsNone(self.other.unsubscribed_at)
        self.assertEqual(self._post(unsubscribe_token(self.sub)).status_code, 200)   # clicking again is harmless
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.unsubscribed_at, first)

    def test_a_tampered_or_made_up_token_is_refused(self):
        from .newsletter import unsubscribe_token
        token = unsubscribe_token(self.sub)
        self.assertEqual(self._post(token[:-2] + 'xx').status_code, 400)
        self.assertEqual(self._post(str(self.sub.pk)).status_code, 400)
        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.unsubscribed_at)
