from django.core.exceptions import ValidationError
from core.testing import TenantTestCase
from django.test import TestCase
from rest_framework.test import APIClient

from .models import ContentStatus, Destination, DestinationTranslation


class PublishGateTests(TenantTestCase):
    def make(self, langs):
        d = Destination.objects.create(slug='ananthagiri')
        for l in langs:
            DestinationTranslation.objects.create(destination=d, language=l, title=f'T-{l}', status=ContentStatus.APPROVED)
        return d

    def test_publish_blocked_without_all_three_approved(self):                   # scenario 15
        d = self.make(['en', 'te'])
        with self.assertRaises(ValidationError) as cm:
            d.publish()
        self.assertIn('HI', cm.exception.messages[0])
        d.refresh_from_db()
        self.assertNotEqual(d.status, ContentStatus.PUBLISHED)

    def test_publish_allowed_when_all_approved_and_public_api_shows_it(self):
        d = self.make(['en', 'te', 'hi'])
        d.publish()
        r = APIClient().get('/api/v1/destinations/?lang=te')
        self.assertEqual(r.data['results'][0]['name'], 'T-te')

    def test_draft_is_not_public(self):
        self.make(['en', 'te', 'hi'])
        self.assertEqual(APIClient().get('/api/v1/destinations/').data['count'], 0)

    def test_workflow_rejects_skipping_review(self):
        d = self.make([])
        t = DestinationTranslation.objects.create(destination=d, language='en', title='x')
        with self.assertRaises(ValidationError):
            t.move_to(ContentStatus.APPROVED)
        for step in (ContentStatus.SUBMITTED, ContentStatus.UNDER_REVIEW, ContentStatus.APPROVED):
            t.move_to(step)
        self.assertEqual(t.status, ContentStatus.APPROVED)
