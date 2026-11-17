import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from tenancy.context import tenant_scope
from tenancy.models import Tenant

from . import models as m

logger = logging.getLogger(__name__)


def _scheduled_models():
    from trips.models import Event, Trip
    return (m.Destination, m.Blog, m.CmsPage, Trip, Event)


@shared_task(name='content.tasks.publish_due')
def publish_due():
    """Every 5 minutes: publish scheduled content whose time has come, for each operator (row-level security needs the
    tenant set). Each record publishes in its own savepoint, so one that fails the English-title check stays scheduled
    and is logged without stopping the rest."""
    published = 0
    for tenant_id in Tenant.objects.filter(is_active=True).values_list('pk', flat=True):
        with tenant_scope(tenant_id):
            for model in _scheduled_models():
                due = model.objects.select_for_update(skip_locked=True).filter(
                    status=m.ContentStatus.SCHEDULED, publish_at__lte=timezone.now())
                for obj in due:
                    try:
                        with transaction.atomic():
                            obj.publish()
                        published += 1
                    except Exception:   # noqa: BLE001 - keep publishing the others
                        logger.exception('Could not publish scheduled %s %s', model.__name__, obj.pk)
    return published
