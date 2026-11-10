import threading
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.testing import make_gst, make_trip, make_user, TenantTestCase
from operations.models import ParticipantWaiverAcceptance, SafetyWaiver
from trips.models import TripSchedule

from .models import Booking
from .services import (BookingError, CheckoutLine, cancel_booking, can_depart, create_checkout, grant_departure_exception, outstanding)


class CheckoutTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()

    def test_multi_trip_checkout_creates_one_booking_per_trip(self):          # scenario 2
        _, s1 = make_trip('a', advance_bp=3000)
        _, s2 = make_trip('b', advance_bp=5000, price='2000.00')
        order = create_checkout(self.user, [CheckoutLine(s1.pk, 2), CheckoutLine(s2.pk, 1)], 'k1')
        self.assertEqual(order.bookings.count(), 2)
        self.assertEqual(order.total_amount, Decimal('12000.00'))

    def test_different_advance_percentages_per_trip(self):                      # scenario 4
        _, s1 = make_trip('a', advance_bp=3000)
        _, s2 = make_trip('b', advance_bp=5000)
        order = create_checkout(self.user, [CheckoutLine(s1.pk, 1), CheckoutLine(s2.pk, 1)], 'k2')
        adv = {b.schedule_id: b.advance_amount for b in order.bookings.all()}
        self.assertEqual(adv[s1.pk], Decimal('1500.00'))
        self.assertEqual(adv[s2.pk], Decimal('2500.00'))

    def test_one_unavailable_trip_blocks_whole_checkout(self):                  # scenario 3
        _, s1 = make_trip('a')
        _, s2 = make_trip('b', capacity=1)
        before = TripSchedule.objects.get(pk=s1.pk).seats_booked
        with self.assertRaises(BookingError) as cm:
            create_checkout(self.user, [CheckoutLine(s1.pk, 2), CheckoutLine(s2.pk, 3)], 'k3')
        self.assertEqual(cm.exception.code, 'checkout_unavailable')
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(TripSchedule.objects.get(pk=s1.pk).seats_booked, before)   # no partial state

    def test_idempotent_replay(self):
        _, s = make_trip('a')
        a = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'same')
        b = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'same')
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Booking.objects.count(), 1)

    def test_gst_exclusive_and_snapshot(self):
        cfg = make_gst(500)
        _, s = make_trip('a', gst=cfg)
        b = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'g').bookings.get()
        self.assertEqual((b.subtotal, b.tax_amount, b.total_amount), (Decimal('5000.00'), Decimal('250.00'), Decimal('5250.00')))
        cfg.rate_basis_points = 1800; cfg.save()
        b.refresh_from_db()
        self.assertEqual(b.tax_amount, Decimal('250.00'))                          # scenario 12: history not recalculated
        self.assertEqual(b.tax_snapshot['rate_basis_points'], 500)

    def test_global_default_and_trip_override(self):
        _, s = make_trip('a')                                                       # no override -> global default 30%
        b = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'd').bookings.get()
        self.assertEqual(b.advance_amount, Decimal('1500.00'))
        _, s2 = make_trip('b', advance_bp=2000)
        b2 = create_checkout(self.user, [CheckoutLine(s2.pk, 1)], 'd2').bookings.get()
        self.assertEqual(b2.advance_amount, Decimal('1000.00'))

    def test_cancel_one_booking_leaves_others(self):                            # scenario 7
        _, s1 = make_trip('a'); _, s2 = make_trip('b')
        order = create_checkout(self.user, [CheckoutLine(s1.pk, 2), CheckoutLine(s2.pk, 2)], 'c')
        b1, b2 = list(order.bookings.order_by('created_at'))
        cancel_booking(b1, self.user)
        b1.refresh_from_db(); b2.refresh_from_db()
        self.assertEqual(b1.status, Booking.Status.CANCELLED)
        self.assertEqual(b2.status, Booking.Status.PENDING_ADVANCE)
        self.assertEqual(TripSchedule.objects.get(pk=b1.schedule_id).seats_booked, 0)   # seats released
        self.assertEqual(TripSchedule.objects.get(pk=b2.schedule_id).seats_booked, 2)

    def test_departure_blocked_until_balance_or_audited_exception(self):        # section 3.2
        _, s = make_trip('a')
        b = create_checkout(self.user, [CheckoutLine(s.pk, 1)], 'x').bookings.get()
        self.assertFalse(can_depart(b))
        staff = make_user('+919000000001', kind='ADMIN', is_staff=True)
        with self.assertRaises(BookingError):                                       # no permission -> refused
            grant_departure_exception(b, staff, 'VIP')


class SafetyWaiverTests(TenantTestCase):
    def setUp(self):
        self.user = make_user()
        _, schedule = make_trip('waiver-test')
        self.booking = create_checkout(self.user, [CheckoutLine(schedule.pk, 1)], 'waiver-test').bookings.get()
        self.booking.participants.create(full_name='Test Participant')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_active_waiver_is_publicly_available(self):
        waiver = SafetyWaiver.objects.create(title='Participation waiver', version=3, body_en='Approved terms.')
        response = APIClient().get('/api/v1/safety-waivers/active/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.data['id'], response.data['version'], response.data['body']),
                         (str(waiver.pk), 3, 'Approved terms.'))

    def test_checkout_cannot_accept_without_active_waiver(self):
        response = APIClient().get('/api/v1/safety-waivers/active/')
        self.assertEqual(response.status_code, 503)
        response = self.client.post(f'/api/v1/bookings/{self.booking.pk}/accept-waiver/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ParticipantWaiverAcceptance.objects.count(), 0)

    def test_whitespace_only_waiver_is_not_usable(self):
        waiver = SafetyWaiver.objects.create(title='Blank terms', version=1, body_en='   \n')
        response = APIClient().get('/api/v1/safety-waivers/active/')
        self.assertEqual(response.status_code, 503)
        response = self.client.post(
            f'/api/v1/bookings/{self.booking.pk}/accept-waiver/',
            {'waiver': str(waiver.pk)},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(ParticipantWaiverAcceptance.objects.count(), 0)

    def test_acceptance_records_the_exact_waiver_version(self):
        waiver = SafetyWaiver.objects.create(title='Participation waiver', version=3, body_en='Approved terms.')
        response = self.client.post(
            f'/api/v1/bookings/{self.booking.pk}/accept-waiver/',
            {'waiver': str(waiver.pk)},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        acceptance = ParticipantWaiverAcceptance.objects.get()
        self.assertEqual(acceptance.waiver_id, waiver.pk)
        self.assertIsNotNone(acceptance.accepted_at)


class OverbookingTests(TransactionTestCase):
    serialized_rollback = True   # the default operator comes from a migration; restore it after the flush
    def test_two_customers_race_for_last_seats(self):                           # scenario 1
        from tenancy.context import tenant_scope
        from tenancy.models import Tenant
        tenant = Tenant.objects.get(slug='gohyderabad')
        with tenant_scope(tenant.pk):                                          # commits, so the worker threads can see it
            _, s = make_trip('race', capacity=2)
            u1, u2 = make_user('+919111111111'), make_user('+919222222222')
        results, barrier = [], threading.Barrier(2)

        def attempt(user, key):
            try:
                barrier.wait()
                with tenant_scope(tenant.pk):                                   # each thread has its own connection and tenant context
                    create_checkout(user, [CheckoutLine(s.pk, 2)], key)
                results.append('ok')
            except BookingError:
                results.append('full')
            finally:
                connection.close()

        ts = [threading.Thread(target=attempt, args=(u1, 'r1')), threading.Thread(target=attempt, args=(u2, 'r2'))]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sorted(results), ['full', 'ok'])
        with tenant_scope(tenant.pk):
            self.assertEqual(TripSchedule.objects.get(pk=s.pk).seats_booked, 2)
