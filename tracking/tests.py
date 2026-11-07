import uuid

from core.testing import TenantTestCase
from django.test import TestCase
from rest_framework.test import APIClient

from .models import TrackingConsent, Visitor, VisitorEvent


class TrackingTests(TenantTestCase):
    def setUp(self):
        self.c = APIClient()
        self.vid = str(uuid.uuid4())

    def collect(self, events, **kw):
        return self.c.post('/api/v1/track/', {'visitor_id': self.vid, 'events': events, **kw}, format='json')

    def test_declined_tracking_stores_no_events(self):                            # scenario 16
        self.c.post('/api/v1/track/consent/', {'visitor_id': self.vid, 'analytics': False}, format='json')
        r = self.collect([{'event_id': 'e1', 'name': 'page_view'}])
        self.assertEqual(r.data['accepted'], 0)
        self.assertEqual(VisitorEvent.objects.count(), 0)

    def test_no_consent_recorded_means_no_events(self):
        self.assertEqual(self.collect([{'event_id': 'e1', 'name': 'page_view'}]).data['accepted'], 0)

    def test_duplicate_event_ignored(self):                                       # scenario 17
        self.c.post('/api/v1/track/consent/', {'visitor_id': self.vid, 'analytics': True}, format='json')
        ev = {'event_id': 'e1', 'name': 'trip_viewed', 'properties': {'trip': 'x'}}
        self.assertEqual(self.collect([ev]).data['accepted'], 1)
        self.assertEqual(self.collect([ev]).data['accepted'], 0)
        self.assertEqual(VisitorEvent.objects.count(), 1)

    def test_sensitive_properties_are_stripped_and_unknown_events_rejected(self):
        self.c.post('/api/v1/track/consent/', {'visitor_id': self.vid, 'analytics': True}, format='json')
        self.collect([{'event_id': 'e2', 'name': 'payment_started', 'properties': {'otp': '123456', 'amount': 5}}])
        self.assertEqual(VisitorEvent.objects.get().properties, {'amount': 5})
        self.assertEqual(self.collect([{'event_id': 'e3', 'name': 'made_up'}]).status_code, 400)

    def test_do_not_track_header_respected(self):
        self.c.post('/api/v1/track/consent/', {'visitor_id': self.vid, 'analytics': True}, format='json')
        r = self.c.post('/api/v1/track/', {'visitor_id': self.vid, 'events': [{'event_id': 'e9', 'name': 'page_view'}]}, format='json', HTTP_DNT='1')
        self.assertEqual(r.data['accepted'], 0)
