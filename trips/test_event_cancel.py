"""Event bookings: the customer cancels online, refunds follow the event's policy, and staff record the UPI refund."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone
from rest_framework.test import APIClient

from admin_api.test_payments import staff_with
from content.models import ContentStatus
from core.models import OutboxEvent
from core.testing import TenantTestCase, make_user
from payments.models import EventRefund

from .models import Event, EventRefundPolicy, EventRegistration, EventSchedule, EventTranslation

PHONE = '+919876543210'
CANCEL = '/api/v1/me/event-bookings/{}/cancel/'
ACTION = '/api/v1/admin/actions/record-event-refund/'


class _Fixture:
    def setUp(self):
        super().setUp()
        self.event = Event.objects.create(slug='box-cricket', status=ContentStatus.PUBLISHED, price=Decimal('500.00'),
                                          cancellation_cutoff_hours=6)
        EventTranslation.objects.create(event=self.event, language='en', title='Box Cricket', status=ContentStatus.PUBLISHED)
        EventRefundPolicy.objects.create(event=self.event, hours_before=48, refund_basis_points=10000)
        EventRefundPolicy.objects.create(event=self.event, hours_before=24, refund_basis_points=5000)
        self.customer = make_user(PHONE)
        self.client_ = APIClient()
        self.client_.force_authenticate(self.customer)

    def _booking(self, hours_ahead=72, status=EventRegistration.Status.CONFIRMED, **kw):
        schedule = EventSchedule.objects.create(event=self.event, starts_at=timezone.now() + timedelta(hours=hours_ahead), capacity=20)
        reg = EventRegistration.objects.create(schedule=schedule, contact_name='Ravi', contact_phone=PHONE, participant_count=2,
                                               status=status, refund_policy_snapshot=self.event.refund_tiers(), **kw)
        return EventRegistration.objects.get(pk=reg.pk)     # as loaded from the database, like every real request

    def _cancel(self, reg, reason='Cannot make it'):
        return self.client_.post(CANCEL.format(reg.reference), {'reason': reason}, format='json')


class CustomerCancelTests(_Fixture, TenantTestCase):

    def test_cancelling_early_refunds_in_full_and_frees_the_places(self):
        reg = self._booking(hours_ahead=72)
        res = self._cancel(reg)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['status'], res.data['cancelled_by_customer']), ('CANCELLED', True))
        self.assertEqual((res.data['refund']['status'], res.data['refund']['amount']), ('DUE', '1000.00'))
        self.assertEqual(reg.schedule.reserved_count(), 0)
        self.assertEqual(EventRegistration.objects.get(pk=reg.pk).cancel_reason, 'Cannot make it')

    def test_refund_follows_the_tier_for_the_time_left(self):
        reg = self._booking(hours_ahead=30)                  # 24h+ tier: 50%
        self.assertEqual(self._cancel(reg).data['refund']['amount'], '500.00')

    def test_after_the_last_tier_the_booking_is_cancelled_without_a_refund(self):
        reg = self._booking(hours_ahead=12)                  # inside every tier, before the 6h cutoff
        res = self._cancel(reg)
        self.assertEqual((res.status_code, res.data['refund']), (200, None))
        self.assertFalse(EventRefund.objects.exists())

    def test_cannot_cancel_after_the_cutoff(self):
        reg = self._booking(hours_ahead=3)
        res = self._cancel(reg)
        self.assertEqual(res.status_code, 400)
        self.assertIn('closed', res.data['detail'])

    def test_unpaid_pending_booking_is_cancelled_with_nothing_to_refund(self):
        reg = self._booking(status=EventRegistration.Status.PENDING)
        self.assertEqual(self._cancel(reg).data['refund'], None)

    def test_pending_booking_with_a_payment_screenshot_gets_a_refund_to_check(self):
        reg = self._booking(status=EventRegistration.Status.PENDING, payment_submitted_at=timezone.now())
        self.assertEqual(self._cancel(reg).data['refund']['amount'], '1000.00')

    def test_only_the_owner_can_cancel(self):
        reg = self._booking()
        stranger = APIClient()
        stranger.force_authenticate(make_user('+919811111111'))
        self.assertEqual(stranger.post(CANCEL.format(reg.reference), {}, format='json').status_code, 404)
        self.assertEqual(APIClient().post(CANCEL.format(reg.reference), {}, format='json').status_code, 401)

    def test_booking_keeps_the_policy_it_was_made_under(self):
        reg = self._booking(hours_ahead=30)
        self.event.refund_policies.all().delete()            # the policy is tightened after booking
        self.assertEqual(self._cancel(reg).data['refund']['amount'], '500.00')

    def test_booking_list_shows_what_cancelling_would_refund(self):
        self._booking(hours_ahead=30)
        row = self.client_.get('/api/v1/me/event-bookings/').data[0]
        self.assertEqual((row['cancellation']['allowed'], row['cancellation']['refund_percent'], row['cancellation']['refund_amount']),
                         (True, 50.0, '500.00'))

    def test_event_page_shows_the_policy(self):
        data = APIClient().get(f'/api/v1/events/{self.event.slug}/').data
        self.assertEqual(data['cancellation_cutoff_hours'], 6)
        self.assertEqual([(p['hours_before'], p['refund_percent']) for p in data['refund_policy']], [(48, 100.0), (24, 50.0)])

    def test_staff_cancelling_a_paid_booking_refunds_in_full(self):
        reg = self._booking(hours_ahead=30)
        reg.status = EventRegistration.Status.CANCELLED
        reg.save()
        self.assertEqual(EventRefund.objects.get(registration=reg).amount, Decimal('1000.00'))


class RecordRefundTests(_Fixture, TenantTestCase):

    def setUp(self):
        super().setUp()
        reg = self._booking()
        self._cancel(reg)
        self.refund = EventRefund.objects.get(registration=reg)
        self.staff, self.staff_client = staff_with('+919822222222', superuser=True)

    def test_recording_a_sent_refund_tells_the_customer(self):
        from notifications.models import NotificationEvent, NotificationJob
        from notifications.tasks import handle_event_booking_event
        res = self.staff_client.post(ACTION, {'refund_id': str(self.refund.pk), 'outcome': 'sent', 'upi_reference': '4321'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.refund.refresh_from_db()
        self.assertEqual((self.refund.status, self.refund.upi_reference, self.refund.recorded_by), ('SENT', '4321', self.staff))
        event = OutboxEvent.objects.get(type='event_booking.refund_sent')
        with mock.patch('notifications.tasks.deliver.delay'):
            handle_event_booking_event(str(event.pk), event.type, event.aggregate_id, {}, str(self.tenant.pk))
        job = NotificationJob.objects.get(event=NotificationEvent.EVENT_REFUND_SENT)
        self.assertEqual((job.recipient_phone, job.context['amount'], job.context['upi_reference']), (PHONE, '1000.00', '4321'))

    def test_a_refund_is_recorded_only_once(self):
        body = {'refund_id': str(self.refund.pk), 'outcome': 'sent'}
        self.staff_client.post(ACTION, body, format='json')
        self.assertEqual(self.staff_client.post(ACTION, body, format='json').status_code, 400)

    def test_not_refunding_needs_a_reason(self):
        body = {'refund_id': str(self.refund.pk), 'outcome': 'not_refunded'}
        self.assertEqual(self.staff_client.post(ACTION, body, format='json').status_code, 400)
        self.assertEqual(self.staff_client.post(ACTION, {**body, 'note': 'Payment never arrived'}, format='json').status_code, 200)
        self.assertFalse(OutboxEvent.objects.filter(type='event_booking.refund_sent').exists())

    def test_amount_cannot_exceed_what_was_paid(self):
        res = self.staff_client.post(ACTION, {'refund_id': str(self.refund.pk), 'outcome': 'sent', 'amount': '1500'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_staff_without_permission_cannot_record(self):
        _, viewer = staff_with('+919833333333', 'view_eventrefund')
        res = viewer.post(ACTION, {'refund_id': str(self.refund.pk), 'outcome': 'sent'}, format='json')
        self.assertEqual(res.status_code, 403)

    def test_payments_page_lists_event_refunds_with_a_summary(self):
        res = self.staff_client.get('/api/v1/admin/lists/payments/', {'type': 'event_refund'})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['counts']['due'], res.data['results'][0]['amount'], res.data['results'][0]['cancelled_by']),
                         (1, '1000.00', 'Customer'))
        self.assertEqual(res.data['summary']['event_refunds_due']['count'], 1)
