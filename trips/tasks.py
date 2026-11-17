from celery import shared_task

from tenancy.context import tenant_scope
from tenancy.models import Tenant

from .event_booking import expire_stale_holds


@shared_task(name='trips.tasks.expire_event_holds')
def expire_event_holds():
    """Hourly: mark event bookings whose unpaid hold ran out as EXPIRED.

    Capacity already ignores lapsed holds, so this releases nothing twice; it keeps admin lists and exports truthful.
    """
    expired = 0
    for tenant_id in Tenant.objects.filter(is_active=True).values_list('pk', flat=True):
        with tenant_scope(tenant_id):
            expired += expire_stale_holds()
    return expired
