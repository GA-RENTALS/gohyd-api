"""GST invoices and credit notes. Numbers are gapless per financial-year series; tax values come from the booking's snapshot."""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import CustomerProfile
from core.money import percent_of, q
from tenancy.context import get_current_tenant

from .models import BusinessEntity, CreditNote, Invoice, InvoiceItem, InvoiceSequence


def financial_year(dt=None):
    dt = dt or timezone.localtime()
    start = dt.year if dt.month >= 4 else dt.year - 1
    return f'{start}-{str(start + 1)[2:]}'


def next_number(prefix):
    series = f'{prefix}-{financial_year()}'
    with transaction.atomic():
        seq, _ = InvoiceSequence.objects.select_for_update().get_or_create(series=series)
        seq.last_value += 1
        seq.save(update_fields=['last_value'])
    return f'{series}/{seq.last_value:05d}'


@transaction.atomic
def issue_invoice(booking):
    """Idempotent: one invoice per booking. Uses the booking's snapshot, never live GST settings."""
    existing = booking.invoices.first()
    if existing:
        return existing
    entity = BusinessEntity.objects.filter(is_default=True).first()
    if not entity:
        raise RuntimeError('Create a default Business entity (legal name, GSTIN) before issuing invoices.')
    prof = CustomerProfile.objects.filter(
        user=booking.primary_booker, tenant_id=booking.tenant_id,
    ).first()
    inv = Invoice.objects.create(
        number=next_number('INV'), booking=booking, entity=entity,
        entity_snapshot={'legal_name': entity.legal_name, 'gstin': entity.gstin, 'address': entity.address, 'state_code': entity.state_code},
        billing_name=(prof.billing_name if prof else '') or booking.primary_booker.full_name,
        billing_gstin=prof.billing_gstin if prof else '', billing_address=prof.billing_address if prof else '',
        currency=booking.currency, subtotal=booking.subtotal, tax_amount=booking.tax_amount, total=booking.total_amount,
        tax_snapshot=booking.tax_snapshot)
    InvoiceItem.objects.create(invoice=inv, description=f'{booking.schedule.trip.slug} - {booking.schedule.starts_at:%d %b %Y}',
                               quantity=booking.participant_count, unit_amount=q(booking.subtotal / booking.participant_count),
                               tax_amount=booking.tax_amount, total=booking.total_amount)
    return inv


@transaction.atomic
def issue_credit_note(refund):
    if hasattr(refund, 'credit_note'):
        return refund.credit_note
    inv = refund.booking.invoices.first()
    if not inv:
        return None
    return CreditNote.objects.create(number=next_number('CN'), invoice=inv, refund=refund, amount=refund.amount, tax_amount=refund.tax_adjustment)
