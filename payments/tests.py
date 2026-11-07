import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from bookings.models import Booking
from bookings.services import BookingError, CheckoutLine, cancel_booking, create_checkout, outstanding, paid_amount
from core.testing import make_entity, make_gst, make_trip, make_user, TenantTestCase
from . import invoicing, services
from .models import Payment, PaymentGatewayEvent, PaymentKind, Refund, RefundTransaction

SECRET = 'whsec_test'


def webhook_body(event, order_id, pay_id='pay_1', eid='evt_1'):
    return json.dumps({'id': eid, 'event': event, 'payload': {'payment': {'entity': {'id': pay_id, 'order_id': order_id, 'fee': 236}}}}).encode()


@override_settings(RAZORPAY_KEY_ID='k', RAZORPAY_KEY_SECRET='s', RAZORPAY_WEBHOOK_SECRET=SECRET)
class PaymentFlowTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        _, self.s1 = make_trip('a', price='5000.00')
        _, self.s2 = make_trip('b', price='2000.00', advance_bp=5000)
        self.order = create_checkout(self.user, [CheckoutLine(self.s1.pk, 1), CheckoutLine(self.s2.pk, 1)], 'co')

    def pay(self, kind, key, order_id, bookings=None):
        with mock.patch('payments.gateway.create_order', return_value={'id': order_id}):
            return services.start_online_payment(self.user, self.order, kind, key, bookings)

    def test_one_payment_covers_several_bookings(self):                         # scenario 5
        p = self.pay('ADVANCE', 'p1', 'order_1')
        self.assertEqual(p.amount, Decimal('2500.00'))      # 1500 + 1000
        services.mark_succeeded(p.pk, 'pay_1')
        self.assertEqual(p.allocations.count(), 2)
        for b in self.order.bookings.all():
            self.assertEqual(b.status, Booking.Status.CONFIRMED)

    def test_balance_paid_separately_before_departure(self):                    # scenario 6
        services.mark_succeeded(self.pay('ADVANCE', 'p1', 'o1').pk, 'pay_1')
        b = self.order.bookings.get(schedule=self.s1)
        self.assertEqual(outstanding(b), Decimal('3500.00'))
        p2 = self.pay('BALANCE', 'p2', 'o2', [b.pk])
        self.assertEqual(p2.amount, Decimal('3500.00'))
        services.mark_succeeded(p2.pk, 'pay_2')
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.FULLY_PAID)
        self.assertEqual(outstanding(b), Decimal('0.00'))
        self.assertEqual(Booking.objects.get(schedule=self.s2).status, Booking.Status.CONFIRMED)   # other booking untouched

    def test_mark_succeeded_is_idempotent(self):
        p = self.pay('ADVANCE', 'p1', 'o1')
        services.mark_succeeded(p.pk, 'pay_1'); services.mark_succeeded(p.pk, 'pay_1')
        self.assertEqual(p.allocations.count(), 2)

    def test_idempotency_key_replays_same_payment(self):
        a = self.pay('ADVANCE', 'same', 'o1'); b = self.pay('ADVANCE', 'same', 'o9')
        self.assertEqual(a.pk, b.pk)

    def test_webhook_marks_paid_when_browser_closed(self):                      # scenario 9
        p = self.pay('ADVANCE', 'p1', 'order_9')
        body = webhook_body('payment.captured', 'order_9')
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(services.handle_webhook(body, sig, json.loads(body)), 'processed')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.SUCCEEDED)
        self.assertEqual(p.gateway_fee, Decimal('2.36'))

    def test_duplicate_webhook_is_ignored(self):                                # scenario 10
        self.pay('ADVANCE', 'p1', 'order_9')
        body = webhook_body('payment.captured', 'order_9')
        sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertEqual(services.handle_webhook(body, sig, json.loads(body)), 'processed')
        self.assertEqual(services.handle_webhook(body, sig, json.loads(body)), 'duplicate')
        self.assertEqual(PaymentGatewayEvent.objects.count(), 1)
        self.assertEqual(Payment.objects.get(gateway_order_id='order_9').allocations.count(), 2)

    def test_bad_webhook_signature_rejected(self):
        self.pay('ADVANCE', 'p1', 'order_9')
        body = webhook_body('payment.captured', 'order_9')
        with self.assertRaises(PermissionError):
            services.handle_webhook(body, 'deadbeef', json.loads(body))
        self.assertEqual(Payment.objects.get(gateway_order_id='order_9').status, Payment.Status.CREATED)

    def test_failed_event_never_overwrites_success(self):
        p = self.pay('ADVANCE', 'p1', 'o1')
        services.mark_succeeded(p.pk, 'pay_1')
        services.mark_failed(p.pk, 'late failure event')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.SUCCEEDED)

    def test_bad_checkout_signature_rejected(self):
        p = self.pay('ADVANCE', 'p1', 'o1')
        with self.assertRaises(BookingError):
            services.confirm_from_client(self.user, p.pk, 'pay_x', 'wrong')
        p.refresh_from_db()
        self.assertEqual(p.status, Payment.Status.CREATED)

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
        services.mark_succeeded(self.pay('ADVANCE', 'p1', 'o1').pk, 'pay_1')
        b1 = self.order.bookings.get(schedule=self.s1)
        cancel_booking(b1, self.user, 'change of plans')
        r = Refund.objects.get(booking=b1)
        self.assertEqual(r.amount, Decimal('1500.00'))                           # 100% tier (20 days out) of the 1500 advance
        self.assertFalse(Refund.objects.filter(booking__schedule=self.s2).exists())
        services.approve_refund(make_user('+919000000003', kind='ADMIN', is_staff=True), r)
        with mock.patch('payments.gateway.create_refund', return_value='rfnd_1'):
            services.process_refund(r.pk)
        rt = RefundTransaction.objects.get(refund=r)
        self.assertEqual((rt.amount, rt.gateway_refund_id), (Decimal('1500.00'), 'rfnd_1'))

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
