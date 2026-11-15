from celery import shared_task

from tenancy.context import tenant_scope
from tenancy.models import Tenant

from .services import expire_unpaid_checkouts as _expire_unpaid_checkouts


@shared_task(name='bookings.tasks.expire_unpaid_checkouts')
def expire_unpaid_checkouts():
    """Every 5 minutes: give back the seats of trip checkouts nobody paid for within the hold time."""
    expired = 0
    for tenant_id in Tenant.objects.filter(is_active=True).values_list('pk', flat=True):
        with tenant_scope(tenant_id):
            expired += _expire_unpaid_checkouts()
    return expired
