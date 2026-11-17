"""Staff actions added for NEXT.md: cancel a whole date, reject a refund, resend skipped messages, scheduled publishing,
hidden unfinished tables, business-setting defaults and the tenant-scoped permission list."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from core.models import AuditLog
from core.testing import TenantTestCase

from .tests import _AdminFixtures

ACTION = '/api/v1/admin/actions/{}/'


class CancelDateTests(_AdminFixtures, TenantTestCase):

    def _paid_advance(self, booking):
        from payments import services
        with mock.patch('payments.gateway.create_order', return_value={'id': f'order-{booking.pk}'}):
            payment = services.start_online_payment(self.customer, booking.checkout, 'ADVANCE', f'k-{booking.pk}')
        services.mark_succeeded(payment.pk, 'pay_1')
        return payment.amount

    def test_cancelling_a_trip_date_cancels_every_booking_with_a_full_refund(self):
        from bookings.models import Booking
        from payments.models import Refund
        _, schedule, booking = self._trip_booking()
        paid = self._paid_advance(booking)
        res = self.client_.post(ACTION.format('cancel-date'), {
            'kind': 'trip', 'schedule_id': str(schedule.pk), 'reason': 'Heavy rain on the route', 'refund': 'full'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['cancelled'], 1)
        booking.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual((schedule.is_open, schedule.seats_booked), (False, 0))
        self.assertIsNotNone(schedule.cancelled_at)
        self.assertEqual(Refund.objects.get(booking=booking).amount, paid)
        self.assertTrue(AuditLog.objects.filter(action='trip_schedule.cancel', entity_id=str(schedule.pk)).exists())
        again = self.client_.post(ACTION.format('cancel-date'), {'kind': 'trip', 'schedule_id': str(schedule.pk), 'reason': 'x'}, format='json')
        self.assertEqual(again.status_code, 400)

    def test_a_reason_is_required(self):
        _, schedule, _ = self._trip_booking()
        res = self.client_.post(ACTION.format('cancel-date'), {'kind': 'trip', 'schedule_id': str(schedule.pk), 'reason': ' '}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('reason', res.data)

    def test_cancelling_an_event_date_refunds_paid_bookings_and_stops_new_ones(self):
        from payments.models import EventRefund
        from trips.models import EventRegistration
        _, schedule = self._event()
        reg = EventRegistration.objects.create(schedule=schedule, contact_name='Ravi', contact_phone='9876500000', participant_count=2)
        reg.status = EventRegistration.Status.CONFIRMED
        reg.save()
        res = self.client_.post(ACTION.format('cancel-date'), {
            'kind': 'event', 'schedule_id': str(schedule.pk), 'reason': 'Venue unavailable'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        reg.refresh_from_db(); schedule.refresh_from_db()
        self.assertEqual(reg.status, EventRegistration.Status.CANCELLED)
        self.assertEqual(EventRefund.objects.get(registration=reg).amount, Decimal('600.00'))
        self.assertIsNotNone(schedule.cancelled_at)
        from rest_framework.test import APIClient
        late = APIClient().post('/api/v1/event-bookings/', {
            'event': 'overview-event', 'schedule': str(schedule.pk), 'name': 'Late', 'phone': '9876500001', 'participant_count': 1,
            'consent_to_contact': True,
        }, format='json')
        self.assertEqual(late.status_code, 400)
        self.assertIn('schedule', late.data)


class RefundAndMessageActionTests(_AdminFixtures, TenantTestCase):

    def test_a_requested_refund_can_be_rejected_once_with_a_reason(self):
        from payments.models import Refund
        _, _, booking = self._trip_booking()
        refund = Refund.objects.create(booking=booking, amount=Decimal('500.00'), reason='Customer cancelled')
        no_reason = self.client_.post(ACTION.format('reject-refund'), {'refund_id': str(refund.pk), 'reason': ''}, format='json')
        self.assertEqual(no_reason.status_code, 400)
        res = self.client_.post(ACTION.format('reject-refund'), {'refund_id': str(refund.pk), 'reason': 'Duplicate request'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.REJECTED)
        self.assertIn('Duplicate request', refund.reason)
        twice = self.client_.post(ACTION.format('reject-refund'), {'refund_id': str(refund.pk), 'reason': 'Again'}, format='json')
        self.assertEqual(twice.status_code, 400)

    def test_skipped_messages_are_queued_again_but_login_codes_are_not(self):
        from notifications.models import NotificationJob
        skipped = NotificationJob.objects.create(user=self.customer, event='booking_confirmation', channel='whatsapp',
                                                 dedupe_key='b1', status=NotificationJob.Status.SKIPPED)
        otp = NotificationJob.objects.create(user=self.customer, event='otp', channel='whatsapp', dedupe_key='o1',
                                             status=NotificationJob.Status.SKIPPED)
        with mock.patch('notifications.tasks.deliver.delay') as deliver, self.captureOnCommitCallbacks(execute=True):
            res = self.client_.post(ACTION.format('resend-notifications'), {}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['queued'], 1)
        deliver.assert_called_once_with(str(skipped.pk), str(self.tenant.pk))
        skipped.refresh_from_db(); otp.refresh_from_db()
        self.assertEqual((skipped.status, otp.status), (NotificationJob.Status.QUEUED, NotificationJob.Status.SKIPPED))


class PublishingAndAdminShapeTests(_AdminFixtures, TenantTestCase):

    def test_scheduled_content_is_published_when_due(self):
        from content.models import Blog, BlogTranslation, ContentStatus
        from content.tasks import publish_due
        blog = Blog.objects.create(slug='due-post')
        BlogTranslation.objects.create(blog=blog, language='en', title='Due post')
        Blog.objects.filter(pk=blog.pk).update(status=ContentStatus.SCHEDULED, publish_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(publish_due(), 1)
        blog.refresh_from_db()
        self.assertEqual(blog.status, ContentStatus.PUBLISHED)

    def test_a_schedule_can_be_cancelled_back_to_draft(self):
        from content.models import Blog, BlogTranslation, ContentStatus
        blog = Blog.objects.create(slug='later-post')
        BlogTranslation.objects.create(blog=blog, language='en', title='Later post')
        when = (timezone.now() + timedelta(days=1)).isoformat()
        body = {'resource': 'blogs', 'id': str(blog.pk)}
        self.assertEqual(self.client_.post(ACTION.format('content-transition'), {**body, 'status': 'SCHEDULED', 'publish_at': when}, format='json').status_code, 200)
        self.assertEqual(self.client_.post(ACTION.format('content-transition'), {**body, 'status': 'DRAFT'}, format='json').status_code, 200)
        blog.refresh_from_db()
        self.assertEqual(blog.status, ContentStatus.DRAFT)

    def test_unfinished_tables_are_left_out_of_all_data(self):
        modules = self.client_.get('/api/v1/admin/modules/').data['modules']
        keys = {r['key'] for m in modules for r in m['resources']}
        self.assertNotIn('settlements', keys)
        self.assertNotIn('analytics-daily', keys)
        self.assertIn('vendor-payments', keys)
        self.assertEqual(self.client_.get('/api/v1/admin/resources/settlements/').status_code, 200)   # still reachable

    def test_business_settings_list_every_known_setting(self):
        from core.models import Setting
        Setting.objects.filter(key='checkout.hold_minutes').delete()
        res = self.client_.get('/api/v1/admin/resources/settings/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('checkout.hold_minutes', [r['key'] for r in res.data['results']])

    def test_a_superusers_session_lists_permissions_for_the_admin_screens(self):
        perms = self.client_.get('/api/v1/admin/session/').data['permissions']
        self.assertIn('bookings.grant_departure_exception', perms)
