from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_trip, TenantTestCase


class TripApiTests(TenantTestCase):
    def test_published_trip_listed_with_schedule_and_effective_advance(self):
        make_trip('ananthagiri', advance_bp=2500)
        r = APIClient().get('/api/v1/trips/')
        self.assertEqual(r.data['count'], 1)
        d = APIClient().get('/api/v1/trips/ananthagiri/').data
        self.assertEqual(d['schedules'][0]['advance_basis_points'], 2500)

    def test_admin_pages_load(self):
        U = get_user_model()
        su = U.objects.create_superuser('+919999999999', password='pw-12345-xyz')
        c = self.client; c.force_login(su)
        for path in ('/admin/?classic=1', '/admin/bookings/booking/', '/admin/payments/payment/', '/admin/trips/trip/add/', '/admin/content/destination/add/',
                     '/admin/crm/enquiry/', '/admin/tracking/visitorevent/', '/admin/core/auditlog/', '/admin/accounts/user/'):
            self.assertEqual(c.get(path).status_code, 200, path)


class EventPopupAndBookingTests(TenantTestCase):
    """The seeded Box Cricket event is public, flagged for the homepage popup, and website bookings link to it in the CRM."""

    def setUp(self):
        import tempfile
        from django.core.management import call_command
        from django.test import override_settings
        tmp = tempfile.mkdtemp()
        self._storage = override_settings(
            MEDIA_ROOT=tmp,
            STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage', 'OPTIONS': {'location': tmp}},
                      'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
        self._storage.enable()
        self.addCleanup(self._storage.disable)
        # Throttle counters live in the cache: use a private, empty one per test instead of the shared Redis.
        self._cache = override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                                            'LOCATION': f'event-tests-{id(self)}'}})
        self._cache.enable()
        self.addCleanup(self._cache.disable)
        from unittest import mock
        import datetime as dt
        from zoneinfo import ZoneInfo
        # Freeze "now" before the event so its date counts as upcoming whenever the suite runs.
        frozen = dt.datetime(2026, 11, 11, 12, 0, tzinfo=ZoneInfo('UTC'))
        patcher = mock.patch('django.utils.timezone.now', return_value=frozen)
        patcher.start()
        self.addCleanup(patcher.stop)
        call_command('seed_box_cricket_event', stdout=open('/dev/null', 'w'))

    def test_seeded_event_is_listed_for_the_popup_with_its_poster(self):
        rows = APIClient().get('/api/v1/events/?lang=en&show_in_popup=true').data['results']
        self.assertEqual([r['slug'] for r in rows], ['box-cricket-community-play-day'])
        row = rows[0]
        self.assertTrue(row['show_in_popup'])
        self.assertTrue(row['popup_banner_url'])
        self.assertIsNotNone(row['next_date'])
        self.assertEqual(row['title'], 'Box Cricket Community Play Day')

    def test_seed_is_idempotent(self):
        from django.core.management import call_command
        from .models import Event
        call_command('seed_box_cricket_event', stdout=open('/dev/null', 'w'))
        event = Event.objects.get(slug='box-cricket-community-play-day')
        self.assertEqual(event.schedules.count(), 1)
        self.assertEqual(event.translations.count(), 3)

    # ---- bookings ----
    SLUG = 'box-cricket-community-play-day'

    def _schedule(self):
        return APIClient().get(f'/api/v1/events/{self.SLUG}/?lang=en').data['schedules'][0]

    def _book(self, count, phone='9876543210', **extra):
        return APIClient().post('/api/v1/event-bookings/', {
            'event': self.SLUG, 'schedule': self._schedule()['id'], 'name': 'Test Player', 'phone': phone,
            'participant_count': count, 'consent_to_contact': True, **extra}, format='json')

    def test_detail_exposes_format_rules_and_capacity(self):
        d = APIClient().get(f'/api/v1/events/{self.SLUG}/?lang=en').data
        self.assertIn({'label': 'Overs per match', 'value': '10'}, d['format_details'])
        self.assertTrue(d['rules'])
        self.assertEqual(d['headline'], 'Play. Connect. Make New Friends.')
        self.assertEqual(len(d['faqs']), 5)
        self.assertIn('Organiser-managed teams', d['highlights'])
        self.assertEqual(d['itineraries'][0]['items'][1]['detail'], 'Meet your teammates and understand the match format.')
        self.assertEqual(d['schedules'][0]['capacity'], 15)
        self.assertEqual(d['schedules'][0]['seats_left'], 15)
        self.assertFalse(d['schedules'][0]['time_tbd'])

    def test_group_booking_holds_slots_with_reference_and_total(self):
        r = self._book(4)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['reference'].startswith('GHE-'))
        self.assertEqual(r.data['status'], 'PENDING')            # never reported as confirmed
        self.assertEqual(str(r.data['total_amount']), '1996.00')  # 4 x 499
        self.assertEqual(r.data['seats_left'], 11)
        from crm.models import Enquiry
        self.assertEqual(Enquiry.objects.get().event.slug, self.SLUG)

    def test_group_larger_than_remaining_capacity_is_rejected(self):
        self.assertEqual(self._book(10).status_code, 201)
        r = self._book(6, phone='9876543211')
        self.assertEqual(r.status_code, 400)
        self.assertIn('participant_count', r.data)
        self.assertEqual(self._book(5, phone='9876543211').status_code, 201)
        self.assertEqual(self._book(1, phone='9876543212').status_code, 400)   # sold out

    def test_expired_hold_releases_capacity(self):
        from .models import EventRegistration
        self.assertEqual(self._book(15).status_code, 201)
        EventRegistration.objects.update(reserved_until=timezone_now() - __import__('datetime').timedelta(minutes=1))
        self.assertEqual(self._schedule()['seats_left'], 15)
        self.assertEqual(self._book(2, phone='9876543211').status_code, 201)

    def test_staff_cannot_confirm_into_overbooking(self):
        from django.core.exceptions import ValidationError
        from .models import EventRegistration
        self.assertEqual(self._book(15).status_code, 201)
        first = EventRegistration.objects.get()
        EventRegistration.objects.filter(pk=first.pk).update(reserved_until=timezone_now() - __import__('datetime').timedelta(minutes=1))
        self.assertEqual(self._book(15, phone='9876543211').status_code, 201)
        first.refresh_from_db()
        first.status = EventRegistration.Status.CONFIRMED
        with self.assertRaises(ValidationError):
            first.full_clean()

    def test_status_lookup_requires_matching_phone(self):
        ref = self._book(2).data['reference']
        ok = APIClient().get(f'/api/v1/event-bookings/{ref}/?phone=9876543210')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.data['status_label'], 'Pending confirmation')
        self.assertEqual(APIClient().get(f'/api/v1/event-bookings/{ref}/?phone=9876543299').status_code, 404)


    def test_signed_in_customer_sees_event_bookings_made_with_their_phone(self):
        from core.testing import make_user
        mine = self._book(2, phone='9876543210').data['reference']
        self._book(1, phone='9876543299')                       # someone else's booking
        self.assertEqual(APIClient().get('/api/v1/me/event-bookings/').status_code, 401)
        client = APIClient()
        client.force_authenticate(make_user('+919876543210'))
        r = client.get('/api/v1/me/event-bookings/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([b['reference'] for b in r.data], [mine])
        self.assertEqual(r.data[0]['status'], 'PENDING')

    def test_staff_typed_phone_is_normalised_and_findable(self):
        from .models import EventRegistration, EventSchedule
        schedule = EventSchedule.objects.get()
        booking = EventRegistration.objects.create(schedule=schedule, contact_name='Phone caller',
                                                   contact_phone='98765 43210', participant_count=2, source='whatsapp')
        self.assertEqual(booking.contact_phone, '+919876543210')
        r = APIClient().get(f'/api/v1/event-bookings/{booking.reference}/?phone=9876543210')
        self.assertEqual(r.status_code, 200)
        self.assertIn('box-cricket-community-play-day', str(schedule))


def timezone_now():
    from django.utils import timezone
    return timezone.now()
