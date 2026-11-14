import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import CustomerProfile
from tenancy.context import get_current_tenant

from .models import Channel, NotificationJob, NotificationTemplate, NotificationTranslation

logger = logging.getLogger(__name__)


# WhatsApp templates use numbered variables ({{1}}, {{2}}, …). When a template is registered with Meta, its variables must follow
# this order for the event. Missing values are sent as "-" because WhatsApp rejects empty variables.
TEMPLATE_PARAMS = {
    'booking_confirmation': ['name', 'reference', 'trip', 'date'],
    'cancellation': ['name', 'reference', 'trip'],
    'balance_reminder': ['name', 'reference', 'amount', 'due_date'],
    'trip_reminder': ['name', 'trip', 'date'],
    'payment_receipt': ['name', 'amount'],
    'event_payment_proof': ['name', 'phone', 'event', 'date', 'participants', 'amount', 'reference'],
    'event_confirmed': ['name', 'event', 'date', 'participants', 'reference'],
    'event_cancelled': ['name', 'event', 'reference'],
}


def template_params(event: str, context: dict) -> list:
    return [str(context.get(key) or '-') for key in TEMPLATE_PARAMS.get(event, ['name'])]


def render(template: NotificationTemplate, language: str, context: dict):
    tr = (template.translations.filter(language=language).first() or template.translations.filter(language='en').first())
    if not tr:
        return '', ''

    class Safe(dict):
        def __missing__(self, k): return '{' + k + '}'
    return tr.subject.format_map(Safe(context)), tr.body.format_map(Safe(context))


def enqueue_to_number(phone, event, context, dedupe_key, language='en'):
    """One WhatsApp job for a number that isn't a customer account (e.g. the event organiser). Duplicates are ignored."""
    try:
        with transaction.atomic():
            return NotificationJob.objects.create(recipient_phone=phone, event=event, channel=Channel.WHATSAPP,
                                                  language=language, context=context, dedupe_key=dedupe_key[:120])
    except IntegrityError:
        return None


def enqueue(user, event, context, dedupe_key, channels=None):
    """Create one job per enabled channel, respecting the user's preferences. Duplicate dedupe_keys are ignored."""
    tenant = get_current_tenant()
    prof = CustomerProfile.objects.filter(user=user, tenant=tenant).first() if tenant else None
    wanted = channels or [c for c, flag in ((Channel.WHATSAPP, getattr(prof, 'notify_whatsapp', True)), (Channel.EMAIL, getattr(prof, 'notify_email', True)),
                                             (Channel.SMS, getattr(prof, 'notify_sms', False))) if flag]
    wanted = list(wanted) + [Channel.IN_APP]
    jobs = []
    for ch in wanted:
        try:
            with transaction.atomic():
                jobs.append(NotificationJob.objects.create(user=user, event=event, channel=ch, language=user.preferred_language,
                                                           context=context, dedupe_key=f'{dedupe_key}:{ch}'))
        except IntegrityError:
            continue
    return jobs
