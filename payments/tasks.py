import logging

from celery import shared_task

from bookings.models import Booking
from core.services import emit
from tenancy.context import tenant_scope

from . import invoicing, services
from .models import Refund

logger = logging.getLogger(__name__)


@shared_task(name='payments.tasks.handle_payment_event')
def handle_payment_event(event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        emit('notification.payment_receipt' if event_type == 'payment.succeeded' else 'notification.payment_failed', aggregate_id, payload)


@shared_task(name='payments.tasks.handle_refund_event', bind=True, max_retries=5, retry_backoff=True)
def handle_refund_event(self, event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        if event_type == 'refund.approved':
            try:
                services.process_refund(aggregate_id)
            except Exception as exc:
                raise self.retry(exc=exc)
        elif event_type == 'refund.processed':
            invoicing.issue_credit_note(Refund.objects.get(pk=aggregate_id))
            emit('notification.refund_processed', aggregate_id, {})


@shared_task(name='payments.tasks.generate_invoice_for_event', bind=True, max_retries=5, retry_backoff=True)
def generate_invoice_for_event(self, event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        try:
            inv = invoicing.issue_invoice(Booking.objects.get(pk=aggregate_id))
            emit('notification.invoice', inv.pk, {'number': inv.number})
        except Exception as exc:
            raise self.retry(exc=exc)
