"""Event bookings paid online through Cashfree: the advance confirms the booking, the balance can follow, a free booking
needs no payment, and refunds go back through Cashfree."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from content.models import ContentStatus
from core.testing import TenantTestCase, cashfree_attempt, fake_cashfree_order, make_user
from payments.models import EventRefund, Payment, Refund

from .models import Event, EventRefundPolicy, EventRegistration, EventSchedule, EventTranslation

BOOK = '/api/v1/event-bookings/'
CREATE_ORDER = '/api/v1/payments/cashfree/create-order/'
VERIFY = '/api/v1/payments/cashfree/verify/{}/'


@override_settings(CASHFREE_APP_ID='TEST_APP', CASHFREE_SECRET_KEY='cf_test_secret', FRONTEND_ORIGIN='https://site.example.com')
class EventOnlinePaymentTests(TenantTestCase):

    def setUp(self):
        self.event = Event.objects.create(slug='kayak-day', status=ContentStatus.PUBLISHED, price=Decimal('1000.00'),
                                          advance_basis_points=3000, cancellation_cutoff_hours=0)
        EventTranslation.objects.create(event=self.event, language='en', title='Kayak Day', status=ContentStatus.PUBLISHED)
        EventRefundPolicy.objects.create(event=self.event, hours_before=48, refund_basis_points=10000)
        self.schedule = EventSchedule.objects.create(event=self.event, starts_at=timezone.now() + timedelta(days=5), capacity=10)
        self.customer = make_user('+919876543210', full_name='Meera')
        self.client_ = APIClient()
        self.client_.force_authenticate(self.customer)

    def _book(self, people=2):
        res = self.client_.post(BOOK, {'event': self.event.slug, 'schedule': str(self.schedule.pk), 'participant_count': people,
                                       'consent_to_contact': True}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def _start(self, reference, kind='ADVANCE'):
        with mock.patch('payments.gateway.create_order', side_effect=fake_cashfree_order) as create:
            res = self.client_.post(CREATE_ORDER, {'event_booking': reference, 'kind': kind}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.order_call = create.call_args.kwargs if create.call_args else None   # None: the open order was reused
        return res.data

    def _return_from_cashfree(self, session, status='SUCCESS'):
        payment = Payment.objects.get(pk=session['payment'])
        with mock.patch('payments.gateway.get_order_payments', return_value=[cashfree_attempt(payment, status)]), \
                mock.patch('payments.gateway.get_order', return_value={'order_status': 'ACTIVE'}):
            return self.client_.get(VERIFY.format(session['order_id']))

    def test_the_advance_confirms_the_booking_and_the_balance_can_follow(self):
        booking = self._book()
        self.assertEqual((booking['status'], booking['total_amount'], booking['advance_amount']), ('PENDING', '2000.00', '600.00'))
        self.assertEqual(booking['pay_now'], {'kind': 'ADVANCE', 'amount': '600.00'})

        session = self._start(booking['reference'])
        self.assertEqual((session['amount'], session['mode']), ('600.00', 'sandbox'))
        self.assertTrue(session['payment_session_id'])
        self.assertEqual(self.order_call['tags']['booking_type'], 'EVENT')
        self.assertEqual(self.order_call['return_url'], f"https://site.example.com/booking/thank-you?order_id={session['order_id']}")

        verified = self._return_from_cashfree(session)
        self.assertEqual((verified.status_code, verified.data['status'], verified.data['event_booking']),
                         (200, 'paid', booking['reference']))
        row = self.client_.get('/api/v1/me/event-bookings/').data[0]
        self.assertEqual((row['status'], row['paid'], row['outstanding']), ('CONFIRMED', '600.00', '1400.00'))
        self.assertEqual(row['pay_now'], {'kind': 'BALANCE', 'amount': '1400.00'})

        balance = self._start(booking['reference'], kind='BALANCE')
        self.assertEqual(balance['amount'], '1400.00')
        self._return_from_cashfree(balance)
        row = self.client_.get('/api/v1/me/event-bookings/').data[0]
        self.assertEqual((row['paid'], row['outstanding'], row['pay_now']), ('2000.00', '0.00', None))

    def test_a_failed_attempt_keeps_the_booking_waiting_for_payment(self):
        booking = self._book()
        session = self._start(booking['reference'])
        self.assertEqual(self._return_from_cashfree(session, status='FAILED').data['status'], 'failed')
        self.assertEqual(EventRegistration.objects.get(reference=booking['reference']).status, EventRegistration.Status.PENDING)
        self.assertEqual(self._start(booking['reference'])['order_id'], session['order_id'])   # retry: same open order

    def test_nobody_else_can_pay_for_or_check_a_booking(self):
        booking = self._book()
        session = self._start(booking['reference'])
        stranger = APIClient()
        stranger.force_authenticate(make_user('+919811111111'))
        self.assertEqual(stranger.post(CREATE_ORDER, {'event_booking': booking['reference'], 'kind': 'ADVANCE'}, format='json').status_code, 404)
        self.assertEqual(stranger.get(VERIFY.format(session['order_id'])).status_code, 404)

    def test_a_free_booking_is_confirmed_with_nothing_to_pay(self):
        Event.objects.filter(pk=self.event.pk).update(price=0, is_free=True)
        booking = self._book()
        self.assertEqual((booking['status'], booking['pay_now']), ('CONFIRMED', None))

    def test_a_payment_after_the_hold_ran_out_is_refunded(self):
        booking = self._book()
        session = self._start(booking['reference'])
        EventRegistration.objects.filter(reference=booking['reference']).update(reserved_until=timezone.now() - timedelta(minutes=1))
        self._return_from_cashfree(session)
        reg = EventRegistration.objects.get(reference=booking['reference'])
        self.assertEqual(reg.status, EventRegistration.Status.PENDING)          # not revived: its places may be gone
        self.assertEqual(Refund.objects.get(event_registration=reg).amount, Decimal('600.00'))

    def test_cancelling_a_booking_paid_online_refunds_through_cashfree(self):
        booking = self._book()
        self._return_from_cashfree(self._start(booking['reference']))
        res = self.client_.post(f"/api/v1/me/event-bookings/{booking['reference']}/cancel/", {'reason': 'Ill'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data['refund']['amount'], res.data['refund']['online']), ('600.00', True))   # what was paid, not the price
        reg = EventRegistration.objects.get(reference=booking['reference'])
        refund = Refund.objects.get(event_registration=reg)
        self.assertEqual(refund.status, Refund.Status.REQUESTED)
        self.assertFalse(EventRefund.objects.exists())

        from payments import services
        services.approve_refund(make_user('+919000000003', kind='ADMIN', is_staff=True), refund)
        with mock.patch('payments.gateway.create_refund', return_value={'cf_refund_id': '1', 'refund_status': 'SUCCESS'}) as create:
            services.process_refund(refund.pk)
        self.assertEqual(create.call_args.kwargs['refund_amount'], Decimal('600.00'))
        self.assertEqual(Refund.objects.get(pk=refund.pk).status, Refund.Status.PROCESSED)

    def test_finance_can_refund_part_of_an_online_payment(self):
        from admin_api.test_payments import staff_with
        booking = self._book()
        self._return_from_cashfree(self._start(booking['reference']))
        reg = EventRegistration.objects.get(reference=booking['reference'])
        _, finance = staff_with('+919822222222', superuser=True)
        too_much = finance.post('/api/v1/admin/actions/issue-refund/', {'event_booking_id': str(reg.pk), 'amount': '700',
                                                                         'reason': 'Goodwill'}, format='json')
        self.assertEqual(too_much.status_code, 400)
        with mock.patch('payments.gateway.create_refund', return_value={'cf_refund_id': '2', 'refund_status': 'PENDING'}), \
                self.captureOnCommitCallbacks(execute=True):
            res = finance.post('/api/v1/admin/actions/issue-refund/', {'event_booking_id': str(reg.pk), 'amount': '200',
                                                                        'reason': 'Kayak swapped for a canoe'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Refund.objects.get(event_registration=reg).status, Refund.Status.APPROVED)
