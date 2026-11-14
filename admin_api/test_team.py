"""Team & roles: inviting staff, changing roles, deactivating, and the rules that stop people locking others out."""
from django.core.management import call_command
from rest_framework.test import APIClient

from core.testing import TenantTestCase, make_user
from tenancy.models import TenantMembership

from .test_payments import staff_with
from .tests import _AdminFixtures

TEAM = '/api/v1/admin/team/'


def tenant_admin(phone):
    """A non-superuser admin of this operator (TENANT_ADMIN membership + the Admin role)."""
    from django.contrib.auth.models import Group
    user = make_user(phone, is_staff=True, full_name=f'Admin {phone[-4:]}')
    TenantMembership.objects.filter(user=user).update(role=TenantMembership.Role.TENANT_ADMIN)
    user.groups.add(Group.objects.get(name='Admin'))
    client = APIClient()
    client.force_authenticate(user)
    return user, client


class TeamPageTests(_AdminFixtures, TenantTestCase):

    def setUp(self):
        super().setUp()
        call_command('seed_platform', verbosity=0)

    def _invite(self, client, phone='98123 45678', role='Finance Manager', name='Priya Finance'):
        return client.post(TEAM, {'name': name, 'phone': phone, 'role': role}, format='json')

    # ---- list ----
    def test_list_shows_staff_and_a_role_matrix(self):
        res = self.client_.get(TEAM)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn('+919811111111', [r['phone'] for r in res.data['results']])
        finance = next(r for r in res.data['roles'] if r['name'] == 'Finance Manager')
        self.assertEqual(finance['access']['payments'], 'full')
        self.assertEqual(finance['access']['website'], '')
        self.assertTrue(res.data['can']['manage'])

    def test_staff_without_access_cannot_see_the_team(self):
        _, viewer = staff_with('+919844444444', 'view_payment')
        self.assertEqual(viewer.get(TEAM).status_code, 403)

    # ---- invite ----
    def test_invited_person_gets_exactly_their_role(self):
        res = self._invite(self.client_)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual((res.data['phone'], res.data['role'], res.data['active']), ('+919812345678', 'Finance Manager', True))

        from accounts.models import User
        person = User.objects.get(phone_number='+919812345678')
        client = APIClient()
        client.force_authenticate(person)
        self.assertEqual(client.get('/api/v1/admin/lists/payments/').status_code, 200)   # Finance can see payments
        self.assertEqual(client.post('/api/v1/admin/resources/trips/', {'slug': 'x'}, format='json').status_code, 403)   # not trips

    def test_existing_customer_can_be_invited_and_keeps_their_account(self):
        res = self._invite(self.client_, phone=self.customer.phone_number, role='Customer Support')
        self.assertEqual(res.status_code, 201, res.data)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_staff)
        self.assertEqual(self.customer.full_name, 'Asha Customer')   # not overwritten

    def test_cannot_invite_someone_already_on_the_team(self):
        self._invite(self.client_)
        again = self._invite(self.client_)
        self.assertEqual(again.status_code, 400)
        self.assertIn('phone', again.data)

    def test_bad_phone_and_unknown_role_are_rejected(self):
        self.assertIn('phone', self._invite(self.client_, phone='12345').data)
        self.assertIn('role', self._invite(self.client_, role='Owner').data)

    def test_only_admins_can_invite(self):
        _, member = staff_with('+919855555555', 'view_tenantmembership')
        self.assertEqual(member.get(TEAM).status_code, 200)            # may look
        self.assertEqual(self._invite(member).status_code, 403)        # may not change
        self.assertFalse(member.get(TEAM).data['can']['manage'])

    def test_tenant_admin_cannot_hand_out_super_admin(self):
        _, admin = tenant_admin('+919866666666')
        self.assertIn('role', self._invite(admin, role='Super Admin').data)
        self.assertEqual(self._invite(admin, role='Admin').status_code, 201)

    # ---- change role / deactivate ----
    def test_deactivated_member_loses_access_on_the_next_request(self):
        person_id = self._invite(self.client_).data['id']
        from accounts.models import User
        person = User.objects.get(pk=person_id)
        client = APIClient()
        client.force_authenticate(person)
        self.assertEqual(client.get('/api/v1/admin/session/').status_code, 200)

        res = self.client_.patch(f'{TEAM}{person_id}/', {'active': False}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(res.data['active'])
        self.assertEqual(client.get('/api/v1/admin/session/').status_code, 403)

    def test_changing_role_replaces_the_old_one(self):
        person_id = self._invite(self.client_).data['id']
        res = self.client_.patch(f'{TEAM}{person_id}/', {'role': 'Booking Manager'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        from accounts.models import User
        self.assertEqual(list(User.objects.get(pk=person_id).groups.values_list('name', flat=True)), ['Booking Manager'])

    def test_nobody_can_change_their_own_access(self):
        user, admin = tenant_admin('+919877777777')
        self.assertEqual(admin.patch(f'{TEAM}{user.pk}/', {'active': False}, format='json').status_code, 403)

    def test_the_last_admin_cannot_be_removed(self):
        only_admin, _ = tenant_admin('+919888888888')
        res = self.client_.patch(f'{TEAM}{only_admin.pk}/', {'role': 'Finance Manager'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('last active admin', res.data['detail'])
        tenant_admin('+919899999999')   # a second admin makes it allowed
        self.assertEqual(self.client_.patch(f'{TEAM}{only_admin.pk}/', {'active': False}, format='json').status_code, 200)

    def test_unknown_member_is_404(self):
        self.assertEqual(self.client_.patch(f'{TEAM}999999/', {'active': False}, format='json').status_code, 404)
        self.assertEqual(self.client_.patch(f'{TEAM}abc/', {'active': False}, format='json').status_code, 404)
