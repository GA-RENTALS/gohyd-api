"""Payments page: verifying manual payments, refunds, the money summary, date filter, duplicate UPI refs and CSV export."""
from decimal import Decimal

from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from core.testing import TenantTestCase, make_user

from .tests import _AdminFixtures

LIST = '/api/v1/admin/lists/payments/'
ACTION = '/api/v1/admin/actions/{}/'


def staff_with(phone, *codenames, superuser=False):
    """A staff member of this operator holding exactly these permissions (e.g. 'view_payment')."""
    user = make_user(phone, is_staff=True, is_superuser=superuser, full_name=f'Staff {phone[-4:]}')
    if codenames:
        user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    client = APIClient()
    client.force_authenticate(user)
    return user, client


class PaymentsPageTests(_AdminFixtures, TenantTestCase):

    def _manual_payment(self):
        """A cash advance on a trip booking, recorded by self.staff and waiting for a second person."""
        _, _, booking = self._trip_booking()
        res = self.client_.post(ACTION.format('record-manual-payment'), {
            'checkout_id': str(booking.checkout_id), 'kind': 'ADVANCE', 'amount': str(booking.advance_amount), 'reference': 'cash-1',
        }, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        return booking, res.data['id']

    # ---- B-01: verification works for a second staff member ----
    def test_second_staff_member_can_verify_a_manual_payment(self):
        from payments.models import Payment
        _, payment_id = self._manual_payment()
        _, checker = staff_with('+919833333333', superuser=True)
        res = checker.post(ACTION.format('verify-payment'), {'payment_id': payment_id, 'approved': True}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Payment.objects.get(pk=payment_id).status, Payment.Status.SUCCEEDED)

    def test_the_person_who_recorded_a_payment_cannot_verify_it(self):
        _, payment_id = self._manual_payment()
        res = self.client_.post(ACTION.format('verify-payment'), {'payment_id': payment_id, 'approved': True}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('different staff member', res.data['detail'])

    def test_view_only_staff_cannot_verify_and_is_not_offered_the_button(self):
        _, payment_id = self._manual_payment()
        _, viewer = staff_with('+919844444444', 'view_payment')
        res = viewer.post(ACTION.format('verify-payment'), {'payment_id': payment_id, 'approved': True}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertFalse(viewer.get(LIST).data['can']['verify'])

    def test_finance_staff_are_offered_the_verify_button(self):
        _, finance = staff_with('+919855555555', 'view_payment', 'change_payment')
        self.assertTrue(finance.get(LIST).data['can']['verify'])

    # ---- list, summary, filters ----
    def test_list_has_summary_and_counts(self):
        self._manual_payment()
        res = self.client_.get(LIST)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['counts']['pending'], 1)
        self.assertEqual(res.data['summary']['to_verify']['count'], 1)
        self.assertIn('received_month', res.data['summary'])
        self.assertIn('balance_due', res.data['summary'])

    def test_date_filter_includes_both_days_and_rejects_bad_dates(self):
        from django.utils import timezone
        self._manual_payment()
        today = timezone.localdate().isoformat()
        self.assertEqual(self.client_.get(f'{LIST}?from={today}&to={today}').data['count'], 1)
        self.assertEqual(self.client_.get(f'{LIST}?from=2000-01-01&to=2000-01-31').data['count'], 0)
        self.assertEqual(self.client_.get(f'{LIST}?from=31-12-2026').status_code, 400)
        self.assertEqual(self.client_.get(f'{LIST}?from={today}&to=2000-01-01').status_code, 400)

    def test_unknown_type_is_rejected(self):
        self.assertEqual(self.client_.get(f'{LIST}?type=nonsense').status_code, 400)

    # ---- refunds tab ----
    def test_refunds_tab_lists_and_approves_requested_refunds(self):
        from payments.models import Refund
        _, _, booking = self._trip_booking()
        refund = Refund.objects.create(booking=booking, amount=Decimal('1000.00'), reason='Customer cancelled')
        res = self.client_.get(f'{LIST}?type=refund&status=pending')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual([r['id'] for r in res.data['results']], [str(refund.pk)])
        self.assertEqual(res.data['summary']['refunds_waiting']['count'], 1)
        self.assertTrue(res.data['can']['approve_refund'])
        approve = self.client_.post(ACTION.format('approve-refund'), {'refund_id': str(refund.pk)}, format='json')
        self.assertEqual(approve.status_code, 200, approve.data)
        self.assertEqual(self.client_.get(f'{LIST}?type=refund').data['counts']['processing'], 1)

    # ---- event UPI proofs ----
    def test_reused_upi_reference_is_flagged(self):
        from trips.models import EventRegistration
        _, schedule = self._event()
        for name in ('First', 'Second'):
            EventRegistration.objects.create(schedule=schedule, contact_name=name, participant_count=1, payment_utr='412345678901')
        EventRegistration.objects.create(schedule=schedule, contact_name='Other', participant_count=1, payment_utr='999999999999')
        rows = self.client_.get(f'{LIST}?type=event').data['results']
        flagged = {r['name']: r['utr_duplicate'] for r in rows}
        self.assertEqual(flagged, {'First': True, 'Second': True, 'Other': False})

    # ---- export ----
    def test_export_returns_the_filtered_rows_as_csv(self):
        self._manual_payment()
        res = self.client_.get(f'{LIST}?status=pending&export=csv')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment; filename="trip-payments-', res['Content-Disposition'])
        lines = res.content.decode('utf-8-sig').strip().splitlines()
        self.assertTrue(lines[0].startswith('Date,Paid by,Phone,Amount'))
        self.assertEqual(len(lines), 2)
        self.assertIn('cash-1', lines[1])


class CsvSafetyTests(TenantTestCase):
    def test_cells_that_look_like_formulas_are_neutralised(self):
        from .listing import _cell
        self.assertEqual(_cell('=HYPERLINK("x")'), '\'=HYPERLINK("x")')
        self.assertEqual(_cell('+91 98765'), "'+91 98765")
        self.assertEqual(_cell('Asha'), 'Asha')
        self.assertEqual(_cell(None), '')
