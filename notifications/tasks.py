import logging
from datetime import timedelta
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

from bookings.models import Booking
from bookings.services import outstanding
from tenancy.context import tenant_scope
from tenancy.models import Tenant

from . import services
from .models import Channel, NotificationEvent, NotificationFailure, NotificationJob

logger = logging.getLogger(__name__)


def _active_tenant_ids():
    return list(Tenant.objects.filter(is_active=True).values_list('pk', flat=True))


def _ctx(b):
    rows = {t.language: t for t in b.schedule.trip.translations.all()}
    title = (rows.get('en') or next(iter(rows.values()), None))
    return {'name': b.primary_booker.full_name or 'there', 'reference': b.reference, 'trip': (title.title if title and title.title else b.schedule.trip.slug),
            'amount': str(outstanding(b)), 'due_date': b.balance_due_at.strftime('%d %b %Y'), 'date': b.schedule.starts_at.strftime('%d %b %Y')}


@shared_task(name='notifications.tasks.handle_booking_event')
def handle_booking_event(event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        b = Booking.objects.select_related('primary_booker', 'schedule__trip').filter(pk=aggregate_id).first()
        if not b:
            return
        ev = {'booking.confirmed': NotificationEvent.BOOKING_CONFIRMATION, 'booking.cancelled': NotificationEvent.CANCELLATION}.get(event_type)
        if ev:
            for job in services.enqueue(b.primary_booker, ev, _ctx(b), f'{event_type}:{b.pk}'):
                deliver.delay(str(job.pk), str(tenant_id))


@shared_task(name='notifications.tasks.send_notification_event')
def send_notification_event(event_id, event_type, aggregate_id, payload, tenant_id):
    with tenant_scope(tenant_id):
        mapping = {'notification.payment_receipt': NotificationEvent.PAYMENT_RECEIPT, 'notification.invoice': NotificationEvent.INVOICE,
                   'notification.refund_processed': NotificationEvent.REFUND}
        ev = mapping.get(event_type)
        if not ev:
            return
        from payments.models import Payment
        p = Payment.objects.select_related('payer').filter(pk=aggregate_id).first() if ev == NotificationEvent.PAYMENT_RECEIPT else None
        if p:
            for job in services.enqueue(p.payer, ev, {'amount': str(p.amount), 'name': p.payer.full_name or 'there'}, f'{event_id}'):
                deliver.delay(str(job.pk), str(tenant_id))


def _event_payment_ctx(r):
    from django.utils import timezone as tz
    ev = r.schedule.event
    rows = {t.language: t for t in ev.translations.all()}
    title = rows.get('en') or next(iter(rows.values()), None)
    start = tz.localtime(r.schedule.starts_at)
    return {'name': r.contact_name or '-', 'phone': r.contact_phone or '-', 'event': (title.title if title and title.title else ev.slug),
            'date': start.strftime('%d %b %Y') if r.schedule.time_tbd else start.strftime('%d %b %Y, %I:%M %p'),
            'participants': str(r.participant_count), 'amount': str(r.total_amount), 'reference': r.reference}


@shared_task(name='notifications.tasks.handle_event_booking_event')
def handle_event_booking_event(event_id, event_type, aggregate_id, payload, tenant_id):
    """event_booking.payment_submitted -> tell the organiser's WhatsApp number who paid."""
    if event_type != 'event_booking.payment_submitted':
        return
    with tenant_scope(tenant_id):
        from trips.models import EventRegistration
        r = (EventRegistration.objects.select_related('schedule__event').prefetch_related('schedule__event__translations')
             .filter(pk=aggregate_id).first())
        if not r:
            return
        ev = r.schedule.event
        number = (ev.payment_alert_number or ev.booking_whatsapp_number or '').strip()
        if number:
            from accounts.models import normalize_phone
            try:
                number = normalize_phone(number)     # staff may type '+91 90593 38727'
            except Exception:  # noqa: BLE001
                logger.warning('Event %s payment alert number %r is not a valid phone number.', ev.slug, number)
                return
        if not number:
            logger.warning('Event %s has no payment alert or booking WhatsApp number; screenshot alert not sent.', ev.slug)
            return
        job = services.enqueue_to_number(number, NotificationEvent.EVENT_PAYMENT_PROOF, _event_payment_ctx(r), f'event-pay:{event_id}')
        if job:
            deliver.delay(str(job.pk), str(tenant_id))


@shared_task(bind=True, max_retries=5, retry_backoff=True, name='notifications.tasks.deliver')
def deliver(self, job_id, tenant_id):
    with tenant_scope(tenant_id):
        job = NotificationJob.objects.select_related('user').get(pk=job_id)
        if job.status in (NotificationJob.Status.SENT, NotificationJob.Status.SKIPPED, NotificationJob.Status.FAILED):
            return

        def skip(reason):
            job.status = NotificationJob.Status.SKIPPED
            job.save(update_fields=['status'])
            NotificationFailure.objects.create(job=job, error=reason[:500], attempt=1)

        if job.channel == Channel.IN_APP:
            job.status, job.sent_at = NotificationJob.Status.SENT, timezone.now()
            job.save(update_fields=['status', 'sent_at'])
            return
        if job.channel != Channel.WHATSAPP:
            job.status = NotificationJob.Status.SKIPPED      # email and SMS providers are not connected yet
            job.save(update_fields=['status'])
            return

        from accounts.services import WhatsAppService
        from .models import NotificationDeliveryLog, NotificationTemplate
        tpl = NotificationTemplate.objects.filter(event=job.event, channel=job.channel, is_active=True).first()
        if not tpl:
            return skip('No active WhatsApp template for this event.')
        if not tpl.provider_template_name:
            return skip('Set the approved WhatsApp template name for this event (Admin: Notifications > Templates).')
        if not WhatsAppService.configured():
            return skip('WhatsApp is not configured (WHATSAPP_API_URL / WHATSAPP_ACCESS_TOKEN).')
        try:
            to = job.recipient_phone or (job.user.phone_number if job.user else '')
            if not to:
                return skip('No phone number to send to.')
            result = WhatsAppService.send_template(to, tpl.provider_template_name, job.language,
                                                   services.template_params(job.event, job.context))
        except Exception as exc:   # noqa: BLE001 - network or Meta rejected it: record, retry, give up after the last try
            NotificationFailure.objects.create(job=job, error=str(exc)[:500], attempt=self.request.retries + 1)
            if self.request.retries >= self.max_retries:
                job.status = NotificationJob.Status.FAILED
                job.save(update_fields=['status'])
                return
            raise self.retry(exc=exc)
        message_id = ((result or {}).get('messages') or [{}])[0].get('id', '')
        NotificationDeliveryLog.objects.create(job=job, provider_message_id=message_id, status='accepted')
        job.status, job.sent_at = NotificationJob.Status.SENT, timezone.now()
        job.save(update_fields=['status', 'sent_at'])


@shared_task(name='notifications.tasks.queue_balance_reminders')
def queue_balance_reminders(days_ahead=3):
    """Hourly: remind customers whose balance falls due within `days_ahead` days (and anyone overdue). Deduped per booking per day."""
    now = timezone.now()
    n = 0
    for tenant_id in _active_tenant_ids():
        with tenant_scope(tenant_id):
            qs = (Booking.objects.filter(status=Booking.Status.CONFIRMED, balance_due_at__lte=now + timedelta(days=days_ahead))
                  .select_related('primary_booker', 'schedule__trip'))
            for b in qs:
                if outstanding(b) <= 0:
                    continue
                for job in services.enqueue(b.primary_booker, NotificationEvent.BALANCE_REMINDER, _ctx(b), f'balance:{b.pk}:{now:%Y%m%d}'):
                    deliver.delay(str(job.pk), str(tenant_id)); n += 1
    return n


@shared_task(name='notifications.tasks.queue_trip_reminders')
def queue_trip_reminders(hours_ahead=48):
    now = timezone.now()
    n = 0
    for tenant_id in _active_tenant_ids():
        with tenant_scope(tenant_id):
            qs = (Booking.objects.filter(status__in=[Booking.Status.CONFIRMED, Booking.Status.FULLY_PAID],
                                         schedule__starts_at__gt=now, schedule__starts_at__lte=now + timedelta(hours=hours_ahead))
                  .select_related('primary_booker', 'schedule__trip'))
            for b in qs:
                for job in services.enqueue(b.primary_booker, NotificationEvent.TRIP_REMINDER, _ctx(b), f'trip:{b.pk}'):
                    deliver.delay(str(job.pk), str(tenant_id)); n += 1
    return n
