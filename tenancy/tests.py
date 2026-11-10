from unittest import mock

from django.core.checks import Error, Warning
from django.test import SimpleTestCase, override_settings

from .checks import tenant_rls_database_check


class TenantRlsDatabaseCheckTests(SimpleTestCase):
    def run_check(self, *, debug, role_flags, vendor='postgresql'):
        connection = mock.MagicMock()
        connection.vendor = vendor
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = role_flags
        with override_settings(DEBUG=debug, TENANT_RLS_ENABLED=True), mock.patch(
            'tenancy.checks.connections', {'default': connection},
        ):
            return tenant_rls_database_check(None)

    def test_development_warns_when_database_role_bypasses_rls(self):
        issues = self.run_check(debug=True, role_flags=(True,))
        self.assertTrue(any(isinstance(issue, Warning) and issue.id == 'tenancy.E004' for issue in issues))

    def test_production_errors_when_database_role_bypasses_rls(self):
        issues = self.run_check(debug=False, role_flags=(True,))
        self.assertTrue(any(isinstance(issue, Error) and issue.id == 'tenancy.E004' for issue in issues))

    def test_limited_database_role_passes(self):
        self.assertEqual(self.run_check(debug=False, role_flags=(False,)), [])
