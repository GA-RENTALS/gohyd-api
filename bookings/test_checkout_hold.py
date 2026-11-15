"""Unpaid trip checkouts hold their seats only for a while (BUGS B-09), and customers can't cancel after departure (B-13)."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import SecurityEvent
from core.testing import TenantTestCase, make_trip, make_user
from crm.models import Coupon, CouponRedemption
from payments import services as payments
from payments.models import Payment, Refund
from trips.models import TripSchedule

from .models import Booking, CheckoutOrder
from .services import BookingError, CheckoutLine, cancel_booking, create_checkout, expire_unpaid_checkouts
from .tasks import expire_unpaid_checkouts as expire_task

HOLD = 30   # settings.CHECKOUT_HOLD_MINUTES


def _age(order, minutes):
    """Pretend the checkout was created `minutes` ago."""
    CheckoutOrder.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))


def _seats(schedule):
    return TripSchedule.objects.get(pk=schedule.pk).seats_booked


@override_settings(RAZORPAY_KEY_ID='k', RAZORPAY_KEY_SECRET='s')
class CheckoutHoldTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        _, self.schedule = make_trip('a', capacity=4)

    def _checkout(self, key='k1', people=2, **kw):
        return create_checkout(self.user, [CheckoutLine(self.schedule.pk, people)], key, **kw)

    def _start_payment(self, order, key='p1'):
        with mock.patch('payments.gateway.create_order', return_value={'id': f'order_{key}'}):
            return payments.start_online_payment(self.user, order, 'ADVANCE', key)

    def test_unpaid_checkout_releases_its_seats_after_the_hold(self):
        order = self._checkout()
        _age(order, HOLD + 1)
        self.assertEqual(expire_task(), 1)
        order.refresh_from_db()
        booking = order.bookings.get()
        self.assertEqual((order.status, booking.status), (CheckoutOrder.Status.EXPIRED, Booking.Status.CANCELLED))
        self.assertEqual(_seats(self.schedule), 0)
        self.assertEqual(booking.cancellation.refund_amount, Decimal('0.00'))     # nothing was paid, nothing to refund

    def test_checkout_within_the_hold_is_kept(self):
        order = self._checkout()
        _age(order, HOLD - 5)
        self.assertEqual(expire_unpaid_checkouts(), 0)
        self.assertEqual(_seats(self.schedule), 2)

    def test_opening_the_payment_window_restarts_the_hold(self):
        order = self._checkout()
        self._start_payment(order)
        _age(order, HOLD + 10)                                           # created long ago, but paying right now
        self.assertEqual(expire_unpaid_checkouts(), 0)
        Payment.objects.filter(checkout=order).update(created_at=timezone.now() - timedelta(minutes=HOLD + 1))
        self.assertEqual(expire_unpaid_checkouts(), 1)                    # payment window abandoned too

    def test_checkout_with_a_payment_to_verify_is_never_expired(self):
        order = self._checkout()
        Payment.objects.create(checkout=order, payer=self.user, kind='ADVANCE', method=Payment.Method.MANUAL, amount=Decimal('3000.00'),
                               status=Payment.Status.PENDING_VERIFICATION, idempotency_key='manual-1')
        _age(order, HOLD * 10)
        self.assertEqual(expire_unpaid_checkouts(), 0)

    def test_pressing_continue_twice_holds_the_seats_once(self):
        first = self._checkout('k1')
        second = self._checkout('k2')
        first.refresh_from_db()
        self.assertEqual(first.status, CheckoutOrder.Status.EXPIRED)
        self.assertEqual((second.status, _seats(self.schedule)), (CheckoutOrder.Status.PENDING, 2))

    def test_replacing_a_checkout_gives_its_coupon_use_back(self):
        Coupon.objects.create(code='ONCE', percent_basis_points=1000, max_redemptions=1)
        self._checkout('k1', coupon_code='ONCE')
        second = self._checkout('k2', coupon_code='ONCE')                 # the first use was never paid
        self.assertEqual(second.coupon.code, 'ONCE')
        self.assertEqual(CouponRedemption.objects.count(), 1)

    def test_a_checkout_that_is_being_paid_is_not_replaced(self):
        first = self._checkout('k1', people=2)
        self._start_payment(first)
        self._checkout('k2', people=2)
        first.refresh_from_db()
        self.assertEqual((first.status, _seats(self.schedule)), (CheckoutOrder.Status.PENDING, 4))

    def test_cannot_start_paying_an_expired_checkout(self):
        order = self._checkout()
        _age(order, HOLD + 1)
        expire_unpaid_checkouts()
        order.refresh_from_db()
        with self.assertRaises(BookingError) as e:
            self._start_payment(order, 'p2')
        self.assertEqual(e.exception.code, 'checkout_expired')

    def test_money_arriving_after_expiry_is_refunded_not_lost(self):
        order = self._checkout()
        payment = self._start_payment(order)
        Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=HOLD + 1))
        _age(order, HOLD + 1)
        self.assertEqual(expire_unpaid_checkouts(), 1)
        payments.mark_succeeded(payment.pk, 'pay_late')                    # the late webhook
        refund = Refund.objects.get(booking=order.bookings.get())
        self.assertEqual((refund.amount, refund.status), (payment.amount, Refund.Status.REQUESTED))
        self.assertTrue(SecurityEvent.objects.filter(kind='payment_after_expiry').exists())

    def test_checkout_api_shows_when_the_hold_ends(self):
        client = APIClient()
        client.force_authenticate(self.user)
        res = client.post('/api/v1/checkouts/', {'items': [{'schedule': str(self.schedule.pk), 'participant_count': 1}]}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNotNone(res.data['hold_until'])


class CustomerCancelAfterDepartureTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        _, self.schedule = make_trip('a')
        self.booking = create_checkout(self.user, [CheckoutLine(self.schedule.pk, 1)], 'k').bookings.get()
        self.client_ = APIClient()
        self.client_.force_authenticate(self.user)

    def _start_trip(self):
        TripSchedule.objects.filter(pk=self.schedule.pk).update(starts_at=timezone.now() - timedelta(hours=1))

    def test_customer_can_cancel_before_the_trip_starts(self):
        self.assertTrue(self.client_.get('/api/v1/bookings/').data['results'][0]['can_cancel'])
        res = self.client_.post(f'/api/v1/bookings/{self.booking.pk}/cancel/', {}, format='json')
        self.assertEqual((res.status_code, res.data['status']), (200, Booking.Status.CANCELLED))

    def test_customer_cannot_cancel_once_the_trip_has_started(self):
        self._start_trip()
        self.assertFalse(self.client_.get('/api/v1/bookings/').data['results'][0]['can_cancel'])
        res = self.client_.post(f'/api/v1/bookings/{self.booking.pk}/cancel/', {}, format='json')
        self.assertEqual((res.status_code, res.data['code']), (400, 'trip_started'))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING_ADVANCE)

    def test_staff_can_still_cancel_after_the_trip_has_started(self):
        self._start_trip()
        staff = make_user('+919800000001', is_staff=True)
        self.assertEqual(cancel_booking(self.booking, staff, 'No-show handled by phone').status, Booking.Status.CANCELLED)
