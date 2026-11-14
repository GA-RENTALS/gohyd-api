"""Event bookings: customer messages on confirm/cancel, the "no price yet" guard, coupons and the published-slug lock."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from content.models import ContentStatus
from core.models import OutboxEvent
from core.testing import TenantTestCase

from .models import Event, EventRegistration, EventSchedule, EventTranslation

BOOK = '/api/v1/event-bookings/'
PREVIEW = '/api/v1/event-bookings/coupon-preview/'


class _EventFixture:
    def setUp(self):
        super().setUp()
        self.event = self._event('sunrise-yoga', price='400.00')
        self.schedule = self.event.schedules.get()

    @staticmethod
    def _event(slug, price='400.00', **kw):
        event = Event.objects.create(slug=slug, status=ContentStatus.PUBLISHED, price=Decimal(price), **kw)
        EventTranslation.objects.create(event=event, language='en', title=slug.replace('-', ' ').title(), status=ContentStatus.PUBLISHED)
        EventSchedule.objects.create(event=event, starts_at=timezone.now() + timedelta(days=5), capacity=20)
        return event

    def _book(self, event=None, count=2, phone='9876543210', **extra):
        event = event or self.event
        return APIClient().post(BOOK, {'event': event.slug, 'schedule': str(event.schedules.get().pk), 'name': 'Ravi',
                                       'phone': phone, 'participant_count': count, 'consent_to_contact': True, **extra}, format='json')


class EventCustomerMessageTests(_EventFixture, TenantTestCase):
    """GAPS G-01."""

    def _outbox(self, reg):
        return list(OutboxEvent.objects.filter(aggregate_id=str(reg.pk)).values_list('type', flat=True))

    def test_confirming_and_cancelling_queue_a_message_once_each(self):
        reg = EventRegistration.objects.create(schedule=self.schedule, contact_name='Ravi', contact_phone='9876543210', participant_count=1)
        self.assertEqual(self._outbox(reg), [])                      # a new pending booking sends nothing
        reg = EventRegistration.objects.get(pk=reg.pk)
        reg.status = EventRegistration.Status.CONFIRMED
        reg.save()
        reg.staff_note = 'Paid in cash'
        reg.save()                                                    # saving again without a status change: no repeat
        reg.status = EventRegistration.Status.CANCELLED
        reg.save()
        self.assertEqual(sorted(self._outbox(reg)), ['event_booking.cancelled', 'event_booking.confirmed'])

    def test_message_goes_to_the_phone_the_customer_booked_with(self):
        from unittest import mock
        from notifications.models import NotificationEvent, NotificationJob
        from notifications.tasks import handle_event_booking_event
        reg = EventRegistration.objects.create(schedule=self.schedule, contact_name='Ravi', contact_phone='9876543210',
                                               participant_count=2, status=EventRegistration.Status.CONFIRMED)
        event = OutboxEvent.objects.get(aggregate_id=str(reg.pk))
        with mock.patch('notifications.tasks.deliver.delay') as deliver:
            handle_event_booking_event(str(event.pk), event.type, str(reg.pk), {}, str(self.tenant.pk))
        job = NotificationJob.objects.get(event=NotificationEvent.EVENT_CONFIRMED)
        self.assertEqual(job.recipient_phone, '+919876543210')
        self.assertEqual((job.context['event'], job.context['participants'], job.context['reference']), ('Sunrise Yoga', '2', reg.reference))
        deliver.assert_called_once()


class EventPriceGuardTests(_EventFixture, TenantTestCase):
    """GAPS G-06 / BUGS B-05: ₹0 means "price not announced", not free."""

    def test_event_without_a_price_does_not_take_bookings(self):
        unpriced = self._event('plan-trek', price='0')
        res = self._book(unpriced)
        self.assertEqual(res.status_code, 400)
        self.assertIn('price is announced', res.data['event'][0])
        self.assertFalse(EventRegistration.objects.filter(schedule__event=unpriced).exists())

    def test_free_events_still_take_bookings(self):
        free = self._event('free-walk', price='0', is_free=True)
        res = self._book(free)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Decimal(res.data['total_amount']), Decimal('0'))
        self.assertTrue(APIClient().get('/api/v1/events/free-walk/').data['is_free'])

    def test_admin_dashboard_warns_about_dated_events_without_a_price(self):
        from admin_api.views import AdminDashboardView
        from core.testing import make_user
        self._event('plan-trek', price='0')
        setup = AdminDashboardView._setup(make_user('+919811111111', is_staff=True, is_superuser=True))
        self.assertIn('event-price', [item['key'] for item in setup])


class EventCouponTests(_EventFixture, TenantTestCase):
    """GAPS G-03."""

    def _coupon(self, code='YOGA10', **kw):
        from crm.models import Coupon
        kw.setdefault('percent_basis_points', 1000)
        return Coupon.objects.create(code=code, **kw)

    def test_coupon_takes_money_off_the_booking(self):
        self._coupon()
        res = self._book(coupon='yoga10')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((Decimal(res.data['discount_amount']), Decimal(res.data['total_amount']), res.data['coupon_code']),
                         (Decimal('80.00'), Decimal('720.00'), 'YOGA10'))

    def test_preview_matches_the_booking(self):
        self._coupon(fixed_amount=Decimal('150'), percent_basis_points=None, code='FLAT150')
        res = APIClient().post(PREVIEW, {'event': self.event.slug, 'participant_count': 2, 'code': 'flat150'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['discount'], res.data['total_after']), (Decimal('150.00'), Decimal('650.00')))

    def test_scope_trip_only_coupons_and_coupons_for_other_events_are_refused(self):
        from core.testing import make_trip
        trip, _ = make_trip('coupon-trip')
        self._coupon('TRIPONLY').trips.add(trip)
        other = self._event('other-event')
        self._coupon('OTHERONLY').events.add(other)
        for code in ('TRIPONLY', 'OTHERONLY'):
            res = self._book(coupon=code)
            self.assertEqual(res.status_code, 400, code)
            self.assertIn('does not apply', res.data['coupon'][0])
        self.assertEqual(self._book(other, coupon='OTHERONLY').status_code, 201)

    def test_event_only_coupon_is_refused_at_trip_checkout(self):
        from bookings.coupons import CouponError, allocate_discount
        coupon = self._coupon('EVENTONLY')
        coupon.events.add(self.event)
        with self.assertRaises(CouponError):
            allocate_discount(coupon, [('a', 'trip-id', Decimal('1000'))])

    def test_limits_count_event_bookings(self):
        self._coupon('ONCEEACH', max_redemptions=2, per_user_limit=1)
        self.assertEqual(self._book(coupon='ONCEEACH', phone='9876500001').status_code, 201)
        again = self._book(coupon='ONCEEACH', phone='9876500001')
        self.assertIn('already used', again.data['coupon'][0])
        self.assertEqual(self._book(coupon='ONCEEACH', phone='9876500002').status_code, 201)
        full = self._book(coupon='ONCEEACH', phone='9876500003')
        self.assertIn('fully used', full.data['coupon'][0])

    def test_cancelled_bookings_give_the_use_back(self):
        self._coupon('ONEONLY', max_redemptions=1)
        ref = self._book(coupon='ONEONLY').data['reference']
        EventRegistration.objects.filter(reference=ref).update(status=EventRegistration.Status.CANCELLED)
        self.assertEqual(self._book(coupon='ONEONLY', phone='9876500009').status_code, 201)


class PublishedSlugTests(_EventFixture, TenantTestCase):
    """GAPS G-08: links (and the homepage photo fallback) depend on the slug, so it is fixed once published."""

    def test_slug_is_locked_after_publishing_but_not_before(self):
        draft = Event.objects.create(slug='draft-event')
        draft.slug = 'renamed-draft'
        draft.full_clean()                                    # never published: fine

        self.event.published_at = timezone.now()
        self.event.save(update_fields=['published_at'])
        self.event.slug = 'new-address'
        with self.assertRaises(ValidationError) as caught:
            self.event.full_clean()
        self.assertIn('slug', caught.exception.message_dict)
