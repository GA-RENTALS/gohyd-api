from unittest import mock

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied

from core.testing import TenantTestCase
from core.management.commands.seed_platform import ROLES
from .registry import RESOURCES
from .views import AdminDashboardView, _require_model_permission


class StaffRolePermissionTests(TenantTestCase):
    def test_seeded_roles_have_expected_admin_boundaries(self):
        call_command('seed_platform', verbosity=0)
        self.assertEqual(set(ROLES), set(Group.objects.filter(name__in=ROLES).values_list('name', flat=True)))

        writer = Group.objects.get(name='Content Writer')
        self.assertTrue(writer.permissions.filter(content_type__app_label='content', codename='add_cmspage').exists())
        self.assertFalse(writer.permissions.filter(content_type__app_label='trips', codename='add_trip').exists())
        self.assertFalse(writer.permissions.filter(content_type__app_label='payments').exists())

        finance = Group.objects.get(name='Finance Manager')
        self.assertTrue(finance.permissions.filter(codename='view_payment').exists())
        self.assertFalse(finance.permissions.filter(codename='add_trip').exists())

        trip_manager = Group.objects.get(name='Trip Manager')
        self.assertTrue(trip_manager.permissions.filter(content_type__app_label='trips', codename='add_trip').exists())


class FinanceResourceAccessTests(SimpleTestCase):
    def test_staff_without_finance_permission_cannot_view_payment_data(self):
        user = mock.Mock(is_authenticated=True, is_staff=True, has_perm=mock.Mock(return_value=False))
        request = mock.Mock(user=user)
        with mock.patch('admin_api.views.has_staff_membership', return_value=True):
            with self.assertRaises(PermissionDenied):
                _require_model_permission(request, RESOURCES['payments'], 'view')


class AdminDashboardSetupTests(SimpleTestCase):
    def test_dashboard_warns_authorized_staff_when_no_usable_waiver_is_active(self):
        user = mock.Mock()
        user.has_perm.side_effect = lambda permission: permission == 'operations.view_safetywaiver'
        with mock.patch('admin_api.views.SafetyWaiver.objects.filter') as filter_waivers:
            filter_waivers.return_value.only.return_value = []
            setup = AdminDashboardView._setup(user)

        self.assertEqual(len(setup), 1)
        self.assertEqual(setup[0]['key'], 'safety-waiver')
        self.assertEqual(setup[0]['severity'], 'warning')
        self.assertEqual(setup[0]['href'], '/admin/logistics/safety-waivers')
