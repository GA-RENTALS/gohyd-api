import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent
from tenancy.context import tenant_scope
from tenancy.models import Tenant

logger = logging.getLogger(__name__)

# event type prefix -> celery task name. Handlers live in their own apps and must be idempotent.
ROUTES = {
    'payment.': 'payments.tasks.handle_payment_event',
    'refund.': 'payments.tasks.handle_refund_event',
    'invoice.': 'payments.tasks.generate_invoice_for_event',
    'booking.': 'notifications.tasks.handle_booking_event',
    'notification.': 'notifications.tasks.send_notification_event',
    'event_booking.': 'notifications.tasks.handle_event_booking_event',
    'analytics.': 'tracking.tasks.handle_analytics_event',
}


@shared_task(name='core.tasks.relay_outbox')
def relay_outbox(batch=50):
    from config.celery import app
    tenant_ids = Tenant.objects.filter(is_active=True).values_list('pk', flat=True)
    dispatched = 0
    for tenant_id in tenant_ids.iterator():
        with tenant_scope(tenant_id):
            with transaction.atomic():
                events = list(OutboxEvent.objects.select_for_update(skip_locked=True)
                              .filter(status=OutboxEvent.Status.PENDING, available_at__lte=timezone.now())[:batch])
                for ev in events:
                    ev.attempts += 1
                    task = next((t for p, t in ROUTES.items() if ev.type.startswith(p)), None)
                    try:
                        if not task:
                            raise LookupError(f'no route for event type {ev.type}')
                        app.send_task(
                            task,
                            args=[str(ev.id), ev.type, ev.aggregate_id, ev.payload, str(tenant_id)],
                            task_id=str(ev.id),
                        )
                        ev.status = OutboxEvent.Status.DISPATCHED
                        ev.dispatched_at = timezone.now()
                        dispatched += 1
                    except Exception as exc:
                        logger.exception('outbox dispatch failed for %s', ev.id)
                        ev.last_error = str(exc)[:500]
                        ev.available_at = timezone.now() + timedelta(seconds=30)
                    ev.save()
    return dispatched
