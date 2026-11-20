import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from bookings.models import Booking
from bookings.services import BookingError, CheckoutLine, cancel_booking, create_checkout, outstanding, paid_amount
from core.testing import (TenantTestCase, cashfree_attempt, cashfree_webhook, fake_cashfree_order, make_entity, make_gst,
                          make_trip, make_user)
from . import invoicing, services
from .models import Payment, PaymentGatewayEvent, PaymentKind, Refund, RefundTransaction

SECRET = 'cf_test_secret'


@override_settings(CASHFREE_APP_ID='TEST_APP', CASHFREE_SECRET_KEY=SECRET, CASHFREE_ORDER_PREFIX='GH', PAYMENT_BRAND='GOHYDERABAD',
                   PUBLIC_API_ORIGIN='https://api.example.com', FRONTEND_ORIGIN='https://site.example.com')
class PaymentFlowTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        _, self.s1 = make_trip('a', price='5000.00')
        _, self.s2 = make_trip('b', price='2000.00', advance_bp=5000)
        self.order = create_checkout(self.user, [CheckoutLine(self.s1.pk, 1), CheckoutLine(self.s2.pk, 1)], 'co')

    def pay(self, kind, key, bookings=None):
        with mock.patch('payments.gateway.create_order', side_effect=fake_cashfree_order) as create:
            p = services.start_online_payment(self.user, self.order, kind, key, bookings)
        self.last_order_call = create.call_args
        return p

    def settle(self, p, attempts):
        """Cashfree reports these attempts for the order; the backend checks and records them."""
        with mock.patch('payments.gateway.get_order_payments', return_value=attempts), \
                mock.patch('payments.gateway.get_order', return_value={'order_status': 'ACTIVE'}):
            return services.reconcile_order(p.gateway_order_id)

    def webhook(self, p, attempt, signature=None):
        body, ts, sig = cashfree_webhook(p.gateway_order_id, attempt)
        with mock.patch('payments.gateway.get_order_payments', return_value=[attempt]), \
                mock.patch('payments.gateway.get_order', return_value={'order_status': 'ACTIVE'}):
            return services.handle_webhook(body, ts, signature or sig, json.loads(body))

    def test_one_payment_covers_several_bookings(self):                         # scenario 5
        p = self.pay('ADVANCE', 'p1')
        self.assertEqual(p.amount, Decimal('2500.00'))      # 1500 + 1000
        services.mark_succeeded(p.pk, 'pay_1')
        self.assertEqual(p.allocations.count(), 2)
        for b in self.order.bookings.all():
            self.assertEqual(b.status, Booking.Status.CONFIRMED)

    def test_the_order_is_branded_and_the_secret_never_reaches_the_browser(self):
        p = self.pay('ADVANCE', 'p1')
        kwargs = self.last_order_call.kwargs
        self.assertTrue(p.gateway_order_id.startswith('GH-'))
        self.assertEqual(kwargs['order_id'], p.gateway_order_id)
        self.assertEqual(kwargs['order_amount'], Decimal('2500.00'))
        self.assertEqual(kwargs['tags']['brand'], 'GOHYDERABAD')
        self.assertEqual(kwargs['notify_url'], 'https://api.example.com/api/v1/payments/cashfree/webhook/')
        self.assertEqual(kwargs['return_url'], f'https://site.example.com/booking/thank-you?order_id={p.gateway_order_id}')
        self.assertEqual(p.gateway_session_id, f'session_{p.gateway_order_id}')

    def test_balance_paid_separately_before_departure(self):                    # scenario 6
        services.mark_succeeded(self.pay('ADVANCE', 'p1').pk, 'pay_1')
        b = self.order.bookings.get(schedule=self.s1)
        self.assertEqual(outstanding(b), Decimal('3500.00'))
        p2 = self.pay('BALANCE', 'p2', [b.pk])
        self.assertEqual(p2.amount, Decimal('3500.00'))
        services.mark_succeeded(p2.pk, 'pay_2')
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.FULLY_PAID)
        self.assertEqual(outstanding(b), Decimal('0.00'))
        self.assertEqual(Booking.objects.get(schedule=self.s2).status, Booking.Status.CONFIRMED)   # other booking untouched

    def test_mark_succeeded_is_idempotent(self):
        p = self.pay('ADVANCE', 'p1')
        services.mark_succeeded(p.pk, 'pay_1'); services.mark_succeeded(p.pk, 'pay_1')
        self.assertEqual(p.allocations.count(), 2)

    def test_idempotency_key_replays_same_payment(self):
        a = self.pay('ADVANCE', 'same'); b = self.pay('ADVANCE', 'same')
        self.assertEqual(a.pk, b.pk)

    def test_returning_from_cashfree_records_a_verified_payment(self):
        p = self.pay('ADVANCE', 'p1')
        payment, outcome = self.settle(p, [cashfree_attempt(p, 'FAILED', cf_payment_id='1'), cashfree_attempt(p)])
        self.assertEqual((outcome, payment.status, payment.gateway_payment_id), ('paid', Payment.Status.SUCCEEDED, str(p.pk.int % 10**10)))

    def test_a_failed_or_abandoned_attempt_leaves_the_order_open_to_retry(self):
        p = self.pay('ADVANCE', 'p1')
        self.assertEqual(self.settle(p, [cashfree_attempt(p, 'FAILED')])[1], 'failed')
        self.assertEqual(self.settle(p, [cashfree_attempt(p, 'USER_DROPPED')])[1], 'cancelled')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.CREATED)
        self.assertEqual(self.pay('ADVANCE', 'retry').pk, p.pk)      # the retry reuses the open order

    def test_an_expired_order_is_closed(self):
        p = self.pay('ADVANCE', 'p1')
        with mock.patch('payments.gateway.get_order_payments', return_value=[]), \
                mock.patch('payments.gateway.get_order', return_value={'order_status': 'EXPIRED'}):
            payment, outcome = services.reconcile_order(p.gateway_order_id)
        self.assertEqual((outcome, payment.status), ('expired', Payment.Status.FAILED))

    def test_a_payment_for_the_wrong_amount_is_not_recorded(self):
        from core.models import SecurityEvent
        p = self.pay('ADVANCE', 'p1')
        _, outcome = self.settle(p, [cashfree_attempt(p, amount=1)])
        p.refresh_from_db()
        self.assertEqual((outcome, p.status), ('pending', Payment.Status.CREATED))
        self.assertTrue(SecurityEvent.objects.filter(kind='payment_amount_mismatch').exists())

    def test_webhook_marks_paid_when_browser_closed(self):                      # scenario 9
        p = self.pay('ADVANCE', 'p1')
        self.assertEqual(self.webhook(p, cashfree_attempt(p)), 'processed')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.SUCCEEDED)

    def test_webhook_for_another_brands_order_is_ignored(self):
        """The merchant account is shared with GoAdventure: its orders may notify this endpoint too."""
        body, ts, sig = cashfree_webhook('GA-12345', {'cf_payment_id': '9', 'payment_status': 'SUCCESS'})
        with mock.patch('payments.gateway.get_order_payments') as lookup:
            self.assertEqual(services.handle_webhook(body, ts, sig, json.loads(body)), 'processed')
        lookup.assert_not_called()

    def test_a_second_start_for_the_same_amount_reuses_the_open_order(self):
        first = self.pay('ADVANCE', 'tab-1')
        second = self.pay('ADVANCE', 'tab-2')
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(Payment.objects.count(), 1)

    def test_a_second_paid_order_never_pays_more_than_the_booking_total(self):
        """Paying the full amount twice: the second payment is refunded, never allocated beyond the total.
        (A second advance would simply count toward the balance, which is still owed.)"""
        from datetime import timedelta
        from django.utils import timezone
        from core.models import SecurityEvent
        first = self.pay('FULL', 'tab-1')
        # An order opened before the hold time ran out is not reused, so a second one can exist and both can be paid.
        Payment.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(hours=3))
        second = self.pay('FULL', 'tab-2')
        self.assertNotEqual(second.pk, first.pk)
        services.mark_succeeded(first.pk, 'pay_1')
        services.mark_succeeded(second.pk, 'pay_2')
        for b in self.order.bookings.all():
            self.assertEqual(paid_amount(b), b.total_amount)
            self.assertEqual(b.status, Booking.Status.FULLY_PAID)
        self.assertEqual(sum(r.amount for r in Refund.objects.all()), second.amount)
        self.assertTrue(SecurityEvent.objects.filter(kind='payment_overpaid').exists())

    def test_a_webhook_that_failed_is_processed_when_cashfree_retries(self):
        p = self.pay('ADVANCE', 'p1')
        with mock.patch('payments.services.mark_succeeded', side_effect=RuntimeError('database blip')):
            with self.assertRaises(RuntimeError):
                self.webhook(p, cashfree_attempt(p))
        event = PaymentGatewayEvent.objects.get()
        self.assertIsNone(event.processed_at)
        self.assertIn('database blip', event.error)
        self.assertEqual(self.webhook(p, cashfree_attempt(p)), 'processed')
        self.assertEqual(self.webhook(p, cashfree_attempt(p)), 'duplicate')
        p.refresh_from_db()
        self.assertEqual((p.status, p.allocations.count()), (Payment.Status.SUCCEEDED, 2))

    def test_duplicate_webhook_is_ignored(self):                                # scenario 10
        p = self.pay('ADVANCE', 'p1')
        self.assertEqual(self.webhook(p, cashfree_attempt(p)), 'processed')
        self.assertEqual(self.webhook(p, cashfree_attempt(p)), 'duplicate')
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)
        self.assertEqual(Payment.objects.get(pk=p.pk).allocations.count(), 2)

    def test_bad_webhook_signature_rejected(self):
        p = self.pay('ADVANCE', 'p1')
        with self.assertRaises(PermissionError):
            self.webhook(p, cashfree_attempt(p), signature='bm90IHRoZSByaWdodCBzaWduYXR1cmU=')
        self.assertEqual(Payment.objects.get(pk=p.pk).status, Payment.Status.CREATED)

    def test_signature_is_checked_over_the_raw_body(self):
        from . import gateway
        body, ts, sig = cashfree_webhook('GH-1', {'payment_status': 'SUCCESS', 'payment_amount': 2500.0})
        self.assertTrue(gateway.verify_webhook_signature(body, ts, sig))
        self.assertFalse(gateway.verify_webhook_signature(body.replace(b'2500.0', b'2500'), ts, sig))   # re-serialised
        self.assertFalse(gateway.verify_webhook_signature(body, str(int(ts) + 1), sig))                  # other timestamp

    def test_failed_event_never_overwrites_success(self):
        p = self.pay('ADVANCE', 'p1')
        services.mark_succeeded(p.pk, 'pay_1')
        services.mark_failed(p.pk, 'late failure event')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.SUCCEEDED)

    def test_manual_payment_needs_second_person_verification(self):             # scenario 11
        staff1, staff2 = make_user('+919000000001', kind='ADMIN', is_staff=True), make_user('+919000000002', kind='ADMIN', is_staff=True)
        p = services.record_manual_payment(staff1, self.order, PaymentKind.ADVANCE, Decimal('2500.00'), 'UPI-123')
        self.assertEqual(p.status, Payment.Status.PENDING_VERIFICATION)
        self.assertEqual(paid_amount(self.order.bookings.first()), 0)           # not counted yet
        with self.assertRaises(BookingError):
            services.verify_manual_payment(staff1, p, True)                      # can't self-verify
        services.verify_manual_payment(staff2, p, True)
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 2)

    def test_manual_payment_wrong_amount_rejected(self):
        staff = make_user('+919000000001', kind='ADMIN', is_staff=True)
        with self.assertRaises(BookingError):
            services.record_manual_payment(staff, self.order, PaymentKind.ADVANCE, Decimal('1.00'), 'oops')

    def test_partial_refund_for_one_booking(self):                              # scenarios 7 & 8
        services.mark_succeeded(self.pay('ADVANCE', 'p1').pk, 'pay_1')
        b1 = self.order.bookings.get(schedule=self.s1)
        cancel_booking(b1, self.user, 'change of plans')
        r = Refund.objects.get(booking=b1)
        self.assertEqual(r.amount, Decimal('1500.00'))                           # 100% tier (20 days out) of the 1500 advance
        self.assertFalse(Refund.objects.filter(booking__schedule=self.s2).exists())
        services.approve_refund(make_user('+919000000003', kind='ADMIN', is_staff=True), r)
        with mock.patch('payments.gateway.create_refund', return_value={'cf_refund_id': '77', 'refund_status': 'PENDING'}) as create:
            services.process_refund(r.pk)
        rt = RefundTransaction.objects.get(refund=r)
        self.assertEqual(rt.amount, Decimal('1500.00'))
        self.assertTrue(rt.gateway_refund_id.startswith('GH-R-'))
        self.assertEqual(create.call_args.kwargs['order_id'], Payment.objects.get(allocations__booking=b1).gateway_order_id)
        self.assertEqual(Refund.objects.get(pk=r.pk).status, Refund.Status.PROCESSING)   # the bank hasn't finished yet
        with mock.patch('payments.gateway.get_refund', return_value={'refund_status': 'SUCCESS', 'refund_arn': 'ARN1'}):
            services.reconcile_refund(rt.gateway_refund_id)
        self.assertEqual(Refund.objects.get(pk=r.pk).status, Refund.Status.PROCESSED)

    def test_invoice_uses_snapshot_and_credit_note_numbers_are_gapless(self):
        make_entity()
        cfg = make_gst(500, default=False)
        _, s = make_trip('gstly', gst=cfg)
        order = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'inv')
        b = order.bookings.get()
        inv = invoicing.issue_invoice(b)
        cfg.rate_basis_points = 1800; cfg.save()
        self.assertEqual(invoicing.issue_invoice(b).pk, inv.pk)                  # idempotent
        self.assertEqual(inv.tax_amount, Decimal('250.00'))
        n1, n2 = invoicing.next_number('INV'), invoicing.next_number('INV')
        self.assertEqual(int(n2.split('/')[1]), int(n1.split('/')[1]) + 1)
