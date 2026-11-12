from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied

from core.testing import TenantTestCase
from core.management.commands.seed_platform import ROLES
from .registry import RESOURCES
from .views import AdminDashboardView, _require_model_permission


class StaffRolePermissionTests(TenantTestCase):
    def test_seeded_roles_have_expected_admin_boundaries(self):
        call_command('seed_platform', verbosity=0)
        self.assertEqual(set(ROLES), set(Group.objects.filter(name__in=ROLES).values_list('name', flat=True)))

        writer = Group.objects.get(name='Content Writer')
        self.assertTrue(writer.permissions.filter(content_type__app_label='content', codename='add_cmspage').exists())
        self.assertFalse(writer.permissions.filter(content_type__app_label='trips', codename='add_trip').exists())
        self.assertFalse(writer.permissions.filter(content_type__app_label='payments').exists())

        finance = Group.objects.get(name='Finance Manager')
        self.assertTrue(finance.permissions.filter(codename='view_payment').exists())
        self.assertFalse(finance.permissions.filter(codename='add_trip').exists())

        trip_manager = Group.objects.get(name='Trip Manager')
        self.assertTrue(trip_manager.permissions.filter(content_type__app_label='trips', codename='add_trip').exists())


class FinanceResourceAccessTests(SimpleTestCase):
    def test_staff_without_finance_permission_cannot_view_payment_data(self):
        user = mock.Mock(is_authenticated=True, is_staff=True, has_perm=mock.Mock(return_value=False))
        request = mock.Mock(user=user)
        with mock.patch('admin_api.views.has_staff_membership', return_value=True):
            with self.assertRaises(PermissionDenied):
                _require_model_permission(request, RESOURCES['payments'], 'view')


class AdminDashboardSetupTests(SimpleTestCase):
    def test_dashboard_warns_authorized_staff_when_no_usable_waiver_is_active(self):
        user = mock.Mock()
        user.has_perm.side_effect = lambda permission: permission == 'operations.view_safetywaiver'
        with mock.patch('admin_api.views.SafetyWaiver.objects.filter') as filter_waivers:
            filter_waivers.return_value.only.return_value = []
            setup = AdminDashboardView._setup(user)

        self.assertEqual(len(setup), 1)
        self.assertEqual(setup[0]['key'], 'safety-waiver')
        self.assertEqual(setup[0]['severity'], 'warning')
        self.assertEqual(setup[0]['href'], '/admin/logistics/safety-waivers')


class _AdminFixtures:
    """A signed-in superuser, a customer, and helpers that create a trip booking or an event."""

    def setUp(self):
        from rest_framework.test import APIClient
        from core.testing import make_user
        self.staff = make_user('+919811111111', is_staff=True, is_superuser=True, full_name='Staff One')
        self.customer = make_user('+919822222222', full_name='Asha Customer')
        self.client_ = APIClient()
        self.client_.force_authenticate(self.staff)

    def _trip_booking(self, slug='overview-trip', people=2, days_ahead=20):
        from bookings.services import CheckoutLine, create_checkout
        from core.testing import make_trip
        trip, schedule = make_trip(slug, advance_bp=3000, days_ahead=days_ahead)
        order = create_checkout(self.customer, [CheckoutLine(schedule.pk, people)], f'key-{slug}')
        return trip, schedule, order.bookings.get()

    def _event(self, capacity=20):
        from datetime import timedelta
        from django.utils import timezone
        from content.models import ContentStatus
        from trips.models import Event, EventSchedule
        event = Event.objects.create(slug='overview-event', status=ContentStatus.PUBLISHED, price=Decimal('300.00'))
        schedule = EventSchedule.objects.create(event=event, starts_at=timezone.now() + timedelta(days=5), capacity=capacity)
        return event, schedule


class AdminCrudAndOverviewTests(_AdminFixtures, TenantTestCase):
    """Safe delete, cancel booking, event check-in and the trip / event overview pages."""

    # ---- safe delete ----
    def test_trip_without_bookings_can_be_deleted(self):
        from core.testing import make_trip
        from trips.models import Trip
        trip, _ = make_trip('empty-trip')
        res = self.client_.delete(f'/api/v1/admin/resources/trips/{trip.pk}/')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Trip.objects.filter(pk=trip.pk).exists())

    def test_trip_with_bookings_is_not_deleted_and_says_why(self):
        from trips.models import Trip
        trip, _, _ = self._trip_booking()
        res = self.client_.delete(f'/api/v1/admin/resources/trips/{trip.pk}/')
        self.assertEqual(res.status_code, 409)
        self.assertIn('1 booking', res.data['detail'])
        self.assertTrue(Trip.objects.filter(pk=trip.pk).exists())

    def test_event_with_bookings_is_not_deleted(self):
        from trips.models import EventRegistration
        event, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='A', participant_count=1)
        res = self.client_.delete(f'/api/v1/admin/resources/events/{event.pk}/')
        self.assertEqual(res.status_code, 409)
        self.assertIn('booking', res.data['detail'])

    # ---- actions ----
    def test_cancel_booking_action_reuses_service_and_releases_seats(self):
        from bookings.models import Booking
        _, schedule, booking = self._trip_booking()
        schedule.refresh_from_db()
        self.assertEqual(schedule.seats_booked, 2)
        res = self.client_.post('/api/v1/admin/actions/cancel-booking/', {'booking_id': str(booking.pk), 'reason': 'Customer asked'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        booking.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(schedule.seats_booked, 0)

    def test_event_check_in_needs_a_confirmed_booking_and_happens_once(self):
        from trips.models import EventAttendance, EventRegistration
        _, schedule = self._event()
        reg = EventRegistration.objects.create(schedule=schedule, contact_name='Ravi', contact_phone='9876500000', participant_count=3)
        url = '/api/v1/admin/actions/event-check-in/'
        self.assertEqual(self.client_.post(url, {'registration_id': str(reg.pk)}, format='json').status_code, 400)   # still pending
        reg.status = EventRegistration.Status.CONFIRMED; reg.save()
        self.assertEqual(self.client_.post(url, {'registration_id': str(reg.pk)}, format='json').status_code, 200)
        self.assertEqual(EventAttendance.objects.filter(participant__registration=reg).count(), 1)
        self.assertEqual(self.client_.post(url, {'registration_id': str(reg.pk)}, format='json').status_code, 400)   # no double check-in

    # ---- overview pages ----
    def test_trip_overview_counts_and_lists(self):
        from bookings.models import BookingParticipant
        trip, schedule, booking = self._trip_booking()
        BookingParticipant.objects.create(booking=booking, full_name='Asha')
        res = self.client_.get(f'/api/v1/admin/overview/trips/{trip.pk}/')
        self.assertEqual(res.status_code, 200, res.data)
        s = res.data['stats']
        self.assertEqual((s['registrations'], s['paid'], s['pending'], s['participants'], s['revenue']), (1, 0, 1, 2, '0.00'))
        self.assertEqual(s['outstanding'], str(booking.total_amount))
        self.assertEqual(res.data['registrations'][0]['reference'], booking.reference)
        self.assertEqual(res.data['registrations'][0]['advance_due'], str(booking.advance_amount))
        self.assertEqual([p['name'] for p in res.data['participants']], ['Asha'])
        self.assertEqual(len(res.data['schedules']), 1)
        # filtering by another date shows nothing
        other = self.client_.get(f'/api/v1/admin/overview/trips/{trip.pk}/?schedule=00000000-0000-0000-0000-000000000000')
        self.assertEqual(other.data['stats']['registrations'], 0)

    def test_event_overview_counts_confirmed_as_paid(self):
        from trips.models import EventRegistration
        event, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='Paid', participant_count=2, status=EventRegistration.Status.CONFIRMED)
        EventRegistration.objects.create(schedule=schedule, contact_name='Waiting', participant_count=1)
        EventRegistration.objects.create(schedule=schedule, contact_name='Gone', participant_count=1, status=EventRegistration.Status.CANCELLED)
        res = self.client_.get(f'/api/v1/admin/overview/events/{event.pk}/')
        self.assertEqual(res.status_code, 200, res.data)
        s = res.data['stats']
        self.assertEqual((s['registrations'], s['paid'], s['pending'], s['cancelled'], s['participants']), (2, 1, 1, 1, 3))
        self.assertEqual((s['revenue'], s['outstanding']), ('600.00', '300.00'))
        self.assertEqual(len(res.data['participants']), 2)   # contact person stands in for each active booking

    def test_overview_unknown_id_is_404(self):
        res = self.client_.get('/api/v1/admin/overview/trips/not-a-uuid/')
        self.assertEqual(res.status_code, 404)

    # ---- card lists + related sections ----
    def test_catalog_lists_trips_with_numbers(self):
        trip, _, booking = self._trip_booking()
        res = self.client_.get('/api/v1/admin/catalog/trips/')
        self.assertEqual(res.status_code, 200, res.data)
        row = next(r for r in res.data['results'] if r['id'] == str(trip.pk))
        self.assertEqual((row['bookings'], row['pending'], row['revenue'], row['next_booked']), (1, 1, '0.00', 2))
        self.assertTrue(res.data['can_create'])

    def test_catalog_lists_events_with_confirmed_revenue(self):
        from trips.models import EventRegistration
        event, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='Paid', participant_count=2, status=EventRegistration.Status.CONFIRMED)
        res = self.client_.get('/api/v1/admin/catalog/events/?search=overview')
        row = next(r for r in res.data['results'] if r['id'] == str(event.pk))
        self.assertEqual((row['bookings'], row['revenue'], row['next_booked']), (1, '600.00', 2))
        self.assertEqual(self.client_.get('/api/v1/admin/catalog/nonsense/').status_code, 404)

    def test_related_records_can_be_listed_by_parent(self):
        from trips.models import EventFAQ
        event, _ = self._event()
        EventFAQ.objects.create(event=event, question_en='Parking?', answer_en='Yes')
        res = self.client_.get(f'/api/v1/admin/resources/event-faqs/?event={event.pk}')
        self.assertEqual([r['question_en'] for r in res.data['results']], ['Parking?'])
        self.assertIn('payments', self.client_.get(f'/api/v1/admin/overview/events/{event.pk}/').data)


class StaffHomeTests(_AdminFixtures, TenantTestCase):
    """Dashboard, list pages, customer page, search and counts."""

    def test_home_returns_todo_and_charts(self):
        from trips.models import EventRegistration
        self._trip_booking(days_ahead=5)
        _, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='Waiting', participant_count=1)
        res = self.client_.get('/api/v1/admin/home/')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data['revenue_30d']), 30)
        self.assertEqual(res.data['todo']['confirm_events']['count'], 1)
        self.assertEqual(res.data['todo']['balance_due']['count'], 1)
        self.assertTrue(any(k['key'] == 'bookings' and k['value'] == 2 for k in res.data['kpis']))
        self.assertEqual(len(res.data['upcoming']), 2)
        self.assertTrue(all(u['title'] for u in res.data['upcoming']))

    def test_booking_lists_with_status_counts(self):
        from trips.models import EventRegistration
        _, _, booking = self._trip_booking()
        res = self.client_.get('/api/v1/admin/lists/bookings/?type=trip&status=awaiting')
        self.assertEqual(res.data['counts'], {'awaiting': 1, 'paid': 0, 'cancelled': 0, 'all': 1})
        self.assertEqual(res.data['results'][0]['reference'], booking.reference)
        self.assertEqual(res.data['results'][0]['name'], 'Asha Customer')
        _, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='Paid', participant_count=1, status='CONFIRMED')
        res = self.client_.get('/api/v1/admin/lists/bookings/?type=event&status=paid&search=paid')
        self.assertEqual([r['name'] for r in res.data['results']], ['Paid'])

    def test_payments_customers_search_and_counts(self):
        _, _, booking = self._trip_booking()
        self.assertEqual(self.client_.get('/api/v1/admin/lists/payments/').status_code, 200)
        self.assertEqual(self.client_.get('/api/v1/admin/lists/payments/?type=event').status_code, 200)
        customers = self.client_.get('/api/v1/admin/lists/customers/?search=Asha').data['results']
        self.assertEqual([(c['name'], c['trip_bookings']) for c in customers], [('Asha Customer', 1)])
        page = self.client_.get(f"/api/v1/admin/customers/{customers[0]['id']}/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.data['trip_bookings'][0]['reference'], booking.reference)
        hits = self.client_.get(f'/api/v1/admin/search/?q={booking.reference}').data['results']
        self.assertTrue(any(h['type'] == 'Trip booking' for h in hits))
        self.assertIn('payments', self.client_.get('/api/v1/admin/counts/').data)
        self.assertEqual(self.client_.get('/api/v1/admin/customers/nope/').status_code, 404)

    def test_image_upload_then_set_as_trip_cover(self):
        import io, tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image
        from core.testing import make_trip
        trip, _ = make_trip('photo-trip')
        schema = self.client_.get('/api/v1/admin/resources/trips/schema/').data
        self.assertTrue(next(f for f in schema['fields'] if f['name'] == 'cover')['media'])
        buf = io.BytesIO(); Image.new('RGB', (40, 30), 'teal').save(buf, 'JPEG')
        tmp = tempfile.mkdtemp()
        storages = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage', 'OPTIONS': {'location': tmp}},
                    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
        with override_settings(MEDIA_ROOT=tmp, STORAGES=storages):
            up = self.client_.post('/api/v1/admin/resources/media-assets/', {
                'file': SimpleUploadedFile('cover.jpg', buf.getvalue(), content_type='image/jpeg'), 'kind': 'image', 'alt_text': 'cover'}, format='multipart')
            self.assertEqual(up.status_code, 201, up.data)
            self.assertTrue(up.data['file'])
            res = self.client_.patch(f'/api/v1/admin/resources/trips/{trip.pk}/', {'cover': up.data['id']}, format='json')
            self.assertEqual(res.status_code, 200, res.data)
        trip.refresh_from_db()
        self.assertEqual(str(trip.cover_id), str(up.data['id']))
