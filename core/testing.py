"""Factories and base classes shared by tests."""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from content.models import ContentStatus
from payments.models import BusinessEntity, GstConfiguration
from trips.models import Trip, TripPolicy, TripSchedule


def make_user(phone='+919876543210', **kw):
    """A user who belongs to the active operator (the app rejects tenant-owned rows that point at outsiders)."""
    from tenancy.context import get_current_tenant
    from tenancy.models import TenantMembership
    user = User.objects.create_user(phone, **kw)
    tenant = get_current_tenant()
    if tenant is not None:
        role = TenantMembership.Role.STAFF if kw.get('is_staff') else TenantMembership.Role.CUSTOMER
        TenantMembership.objects.get_or_create(tenant=tenant, user=user, defaults={'role': role})
    return user


def make_trip(slug='ananthagiri', advance_bp=None, gst=None, days_ahead=20, capacity=10, price='5000.00', policies=True, **kw):
    trip = Trip.objects.create(slug=slug, status=ContentStatus.PUBLISHED, advance_basis_points=advance_bp, gst_configuration=gst, **kw)
    sched = TripSchedule.objects.create(trip=trip, starts_at=timezone.now() + timedelta(days=days_ahead),
                                        ends_at=timezone.now() + timedelta(days=days_ahead, hours=10), capacity=capacity, price_per_participant=Decimal(price))
    if policies:
        TripPolicy.objects.create(trip=trip, days_before=7, refund_basis_points=10000)
        TripPolicy.objects.create(trip=trip, days_before=2, refund_basis_points=5000)
    return trip, sched


def make_gst(bp=500, inclusive=False, default=False):
    return GstConfiguration.objects.create(name=f'GST {bp}', enabled=True, price_includes_tax=inclusive, rate_basis_points=bp,
                                           components=[{'name': 'CGST', 'bp': bp // 2}, {'name': 'SGST', 'bp': bp // 2}], effective_from=timezone.now(), is_default=default)


def make_entity():
    return BusinessEntity.objects.create(legal_name='GoHyderabad Pvt Ltd', gstin='36ABCDE1234F1Z5', is_default=True)


class TenantTestCase(TestCase):
    """Every test runs as the default operator (the tenancy migration creates it), so tenant-owned rows can be written and read.

    The database enforces tenant isolation with row-level security, so the tenant must be set on the connection as well as in Python.
    """

    def _pre_setup(self):
        super()._pre_setup()
        from tenancy.context import set_current_tenant
        from tenancy.models import Tenant
        self.tenant = Tenant.objects.get(slug='gohyderabad')
        self._tenant_token = set_current_tenant(self.tenant)
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(self.tenant.pk)])

    def _post_teardown(self):
        from tenancy.context import reset_current_tenant
        reset_current_tenant(self._tenant_token)
        super()._post_teardown()
