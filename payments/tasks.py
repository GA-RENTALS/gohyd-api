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
            refund = Refund.objects.get(pk=aggregate_id)
            if refund.booking_id:   # trips have a tax invoice to credit; event bookings don't
                invoicing.issue_credit_note(refund)
            emit('notification.refund_processed', aggregate_id, {})


@shared_task(name='payments.tasks.generate_invoice_for_event', bind=True, max_retries=5, retry_backoff=True)
def generate_invoice_for_event(self, event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        try:
            inv = invoicing.issue_invoice(Booking.objects.get(pk=aggregate_id))
            emit('notification.invoice', inv.pk, {'number': inv.number})
        except Exception as exc:
            raise self.retry(exc=exc)


@shared_task(name='payments.tasks.reconcile_with_cashfree')
def reconcile_with_cashfree():
    """Every 10 minutes: ask Cashfree about orders and refunds still open, in case a notification never arrived
    (the customer closed the browser, a webhook failed). Orders older than two days have expired at Cashfree anyway."""
    from datetime import timedelta
    from django.utils import timezone
    from tenancy.models import Tenant
    from . import gateway
    from .models import Payment, RefundTransaction
    if not gateway.configured():
        return 0
    now = timezone.now()
    checked = 0
    for tenant_id in Tenant.objects.filter(is_active=True).values_list('pk', flat=True):
        with tenant_scope(tenant_id):
            open_orders = (Payment.objects.filter(method=Payment.Method.CASHFREE, status=Payment.Status.CREATED,
                                                  created_at__lt=now - timedelta(minutes=10), created_at__gt=now - timedelta(days=2))
                           .exclude(gateway_order_id=None).values_list('gateway_order_id', flat=True))
            for order_id in open_orders:
                try:
                    services.reconcile_order(order_id)
                    checked += 1
                except Exception:   # noqa: BLE001 - one bad order must not stop the rest
                    logger.exception('Could not check Cashfree order %s', order_id)
            for refund_id in RefundTransaction.objects.filter(status=Refund.Status.PROCESSING).values_list('gateway_refund_id', flat=True):
                try:
                    services.reconcile_refund(refund_id)
                    checked += 1
                except Exception:   # noqa: BLE001
                    logger.exception('Could not check Cashfree refund %s', refund_id)
    return checked

