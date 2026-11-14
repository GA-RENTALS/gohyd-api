"""Customers page: totals without double counting, filters, sorting, export, blocking, notes and the search link."""
from decimal import Decimal

from rest_framework.test import APIClient

from core.testing import TenantTestCase, make_user

from .test_payments import staff_with
from .tests import _AdminFixtures

LIST = '/api/v1/admin/lists/customers/'


class CustomersPageTests(_AdminFixtures, TenantTestCase):

    def _repeat_customer(self):
        """self.customer: one unpaid trip booking + one confirmed event booking made without signing in (matched by phone)."""
        from trips.models import EventRegistration
        self._trip_booking()
        _, schedule = self._event()
        EventRegistration.objects.create(schedule=schedule, contact_name='Asha', contact_phone=self.customer.phone_number,
                                         participant_count=2, status=EventRegistration.Status.CONFIRMED)

    def _row(self, data, customer):
        return next(r for r in data['results'] if r['id'] == str(customer.pk))

    # ---- totals and filters ----
    def test_totals_count_trip_and_phone_matched_event_bookings_once(self):
        self._repeat_customer()
        res = self.client_.get(LIST)
        self.assertEqual(res.status_code, 200, res.data)
        row = self._row(res.data, self.customer)
        self.assertEqual((row['trip_bookings'], row['event_bookings'], row['spent']), (1, 1, '600.00'))
        self.assertGreater(Decimal(row['due']), 0)

    def test_filters_find_upcoming_due_and_repeat_customers(self):
        self._repeat_customer()
        quiet = make_user('+919811110000', full_name='No Bookings')
        for bucket in ('upcoming', 'due', 'repeat'):
            ids = [r['id'] for r in self.client_.get(f'{LIST}?status={bucket}').data['results']]
            self.assertIn(str(self.customer.pk), ids, bucket)
            self.assertNotIn(str(quiet.pk), ids, bucket)
        counts = self.client_.get(LIST).data['counts']
        self.assertEqual((counts['repeat'], counts['blocked']), (1, 0))

    def test_sort_by_spent_puts_the_biggest_spender_first(self):
        self._repeat_customer()
        make_user('+919811110001', full_name='Zero Spend')
        first = self.client_.get(f'{LIST}?sort=spent').data['results'][0]
        self.assertEqual(first['id'], str(self.customer.pk))

    def test_joined_date_filter(self):
        self.assertEqual(self.client_.get(f'{LIST}?from=2000-01-01&to=2000-01-02').data['count'], 0)

    def test_summary_and_export(self):
        self._repeat_customer()
        summary = self.client_.get(LIST).data['summary']
        self.assertEqual((summary['with_due'], summary['blocked']), (1, 0))
        res = self.client_.get(f'{LIST}?status=repeat&export=csv')
        lines = res.content.decode('utf-8-sig').strip().splitlines()
        self.assertEqual(lines[0], 'Name,Phone,Email,Joined,Trip bookings,Event bookings,Spent,Due,Active')
        self.assertEqual(len(lines), 2)
        self.assertIn('Asha Customer', lines[1])

    # ---- block / unblock ----
    def test_blocking_needs_a_reason_and_signs_the_customer_out(self):
        url = f'/api/v1/admin/customers/{self.customer.pk}/block/'
        self.assertIn('reason', self.client_.post(url, {'blocked': True}, format='json').data)

        customer_client = APIClient()
        customer_client.force_authenticate(self.customer)
        res = self.client_.post(url, {'blocked': True, 'reason': 'Fake payment screenshots'}, format='json')
        self.assertEqual((res.status_code, res.data['active']), (200, False))
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        detail = self.client_.get(f'/api/v1/admin/customers/{self.customer.pk}/').data
        self.assertIn('Blocked: Fake payment screenshots', [n['text'] for n in detail['notes']])
        self.assertEqual(self.client_.get(f'{LIST}?status=blocked').data['count'], 1)

        self.assertTrue(self.client_.post(url, {'blocked': False}, format='json').data['active'])

    def test_staff_cannot_be_blocked_here_and_permission_is_required(self):
        staff_customer = make_user('+919822220000', is_staff=True)
        from tenancy.models import TenantMembership
        TenantMembership.objects.filter(user=staff_customer).update(role=TenantMembership.Role.CUSTOMER)
        staff_customer.kind = staff_customer.Kind.CUSTOMER
        staff_customer.save(update_fields=['kind'])
        res = self.client_.post(f'/api/v1/admin/customers/{staff_customer.pk}/block/', {'blocked': True, 'reason': 'x'}, format='json')
        self.assertEqual(res.status_code, 400)

        _, viewer = staff_with('+919844444444', 'view_user')
        denied = viewer.post(f'/api/v1/admin/customers/{self.customer.pk}/block/', {'blocked': True, 'reason': 'x'}, format='json')
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(viewer.get(f'/api/v1/admin/customers/{self.customer.pk}/').data['can_block'])

    # ---- notes ----
    def test_staff_notes_are_added_and_listed_newest_first(self):
        url = f'/api/v1/admin/customers/{self.customer.pk}/notes/'
        self.client_.post(url, {'text': 'Prefers Telugu'}, format='json')
        res = self.client_.post(url, {'text': 'Called about the Ananthagiri trip', 'channel': 'call'}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual([(n['channel'], n['text']) for n in res.data][:2],
                         [('call', 'Called about the Ananthagiri trip'), ('note', 'Prefers Telugu')])
        self.assertEqual(self.client_.post(url, {'text': '  '}, format='json').status_code, 400)

    def test_unknown_customer_is_404(self):
        self.assertEqual(self.client_.get('/api/v1/admin/customers/not-a-number/').status_code, 404)
        self.assertEqual(self.client_.post('/api/v1/admin/customers/999999/notes/', {'text': 'x'}, format='json').status_code, 404)

    # ---- B-02 ----
    def test_search_links_customers_to_their_page(self):
        hits = self.client_.get('/api/v1/admin/search/?q=Asha').data['results']
        customer = next(h for h in hits if h['type'] == 'Customer')
        self.assertEqual(customer['href'], f'/admin/customer/{self.customer.pk}')


class SessionFeatureTests(_AdminFixtures, TenantTestCase):
    def test_team_page_flag_follows_access(self):
        self.assertTrue(self.client_.get('/api/v1/admin/session/').data['features']['team'])
        _, viewer = staff_with('+919844444444', 'view_payment')
        self.assertFalse(viewer.get('/api/v1/admin/session/').data['features']['team'])
