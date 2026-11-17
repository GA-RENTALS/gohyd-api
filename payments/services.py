"""Payment orchestration. The browser is never trusted for payment status: success comes from a verified signature or webhook."""
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, CheckoutOrder
from bookings.services import (BookingError, checkout_hold_minutes, checkout_status, outstanding, paid_amount,
                               refresh_booking_status)
from core.models import SecurityEvent
from core.services import audit, emit

from . import gateway
from .models import (Payment, PaymentAllocation, PaymentGatewayEvent, PaymentKind, PaymentTransaction, PaymentVerification,
                     Refund, RefundTransaction)

logger = logging.getLogger(__name__)


def _txn(payment, event, status, raw=None):
    PaymentTransaction.objects.create(payment=payment, event=event, status=status, amount=payment.amount, raw=raw)


def amounts_due(bookings, kind):
    """Server-side computation of what each booking owes for this payment kind."""
    out = {}
    for b in bookings:
        if b.status == Booking.Status.CANCELLED:
            continue
        paid = paid_amount(b)
        if kind == PaymentKind.ADVANCE:
            due = max(Decimal('0.00'), b.advance_amount - paid)
        else:  # BALANCE / FULL: everything outstanding
            due = outstanding(b)
        if due > 0:
            out[b.pk] = due
    return out


@transaction.atomic
def start_online_payment(user, checkout: CheckoutOrder, kind: str, idempotency_key: str, booking_ids=None):
    """Create (or replay) a gateway order covering one or several bookings of a checkout.

    A second request for the same amount (another tab, a retry after a lost confirmation) gets the order that is still
    open instead of a new one, so the customer can't be charged twice for one balance. Should two orders settle anyway,
    `mark_succeeded` allocates only what is still due and requests a refund for the rest.
    """
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.payer_id != user.pk:
            raise BookingError('Idempotency key already used.', 'idempotency_conflict')
        return existing
    # One payment start per checkout at a time: a concurrent request waits here, then sees the order this one made.
    checkout = CheckoutOrder.objects.select_for_update().get(pk=checkout.pk)
    if checkout.status == CheckoutOrder.Status.EXPIRED:
        raise BookingError('This checkout expired and its seats were released. Please book again from the trip page.',
                           'checkout_expired')
    bookings = list(checkout.bookings.select_for_update().all())
    if booking_ids:
        bookings = [b for b in bookings if str(b.pk) in {str(i) for i in booking_ids}]
    due = amounts_due(bookings, kind)
    if not due:
        raise BookingError('Nothing is due for these bookings.', 'nothing_due')
    plan = {str(k): str(v) for k, v in due.items()}
    reusable = _open_payment_for(checkout, user, kind, plan)
    if reusable:
        return reusable
    total = sum(due.values(), Decimal('0.00'))
    p = Payment.objects.create(checkout=checkout, payer=user, kind=kind, method=Payment.Method.RAZORPAY, amount=total,
                               idempotency_key=idempotency_key)
    # stash the allocation plan so webhook/verify can allocate without trusting the client
    _txn(p, 'created', Payment.Status.CREATED, raw={'plan': plan})
    order = gateway.create_order(total, receipt=str(p.pk), notes={'payment_id': str(p.pk), 'checkout': checkout.reference})
    p.gateway_order_id = order['id']
    p.save(update_fields=['gateway_order_id', 'updated_at'])
    return p


def _open_payment_for(checkout, user, kind, plan):
    """A gateway order opened within the hold time for exactly this plan, which the customer can still pay."""
    since = timezone.now() - timedelta(minutes=checkout_hold_minutes())
    candidates = (Payment.objects.filter(checkout=checkout, payer=user, kind=kind, method=Payment.Method.RAZORPAY,
                                         status=Payment.Status.CREATED, created_at__gte=since)
                  .filter(gateway_order_id__gt='').order_by('-created_at'))
    return next((p for p in candidates if {k: str(v) for k, v in _plan(p).items()} == plan), None)


def _plan(payment):
    t = payment.transactions.filter(event='created').first()
    return {k: Decimal(v) for k, v in (t.raw or {}).get('plan', {}).items()} if t else {}


@transaction.atomic
def mark_succeeded(payment_id, gateway_payment_id=None, raw=None, fee=None):
    """Idempotent. Allocates the payment across bookings per the stored plan, updates statuses, emits outbox events."""
    p = Payment.objects.select_for_update().get(pk=payment_id)
    if p.status == Payment.Status.SUCCEEDED:
        return p, False
    p.status = Payment.Status.SUCCEEDED
    if gateway_payment_id:
        p.gateway_payment_id = gateway_payment_id
    if fee is not None:
        p.gateway_fee = fee
    p.save()
    _txn(p, 'succeeded', Payment.Status.SUCCEEDED, raw)
    plan = _plan(p) or {}
    allocated, overpaid = Decimal('0.00'), {}
    for booking_id, amt in plan.items():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        # Allocate only what is still owed: another order for the same balance may have settled first.
        # A cancelled booking takes the whole amount here and is refunded below (_refund_late_payment).
        take = amt if booking.status == Booking.Status.CANCELLED else min(amt, outstanding(booking))
        if take > 0:
            PaymentAllocation.objects.create(payment=p, booking_id=booking_id, kind=p.kind, amount=take)
            allocated += take
        if take < amt:
            overpaid[booking_id] = amt - take
    if allocated + sum(overpaid.values(), Decimal('0.00')) != p.amount:
        # never silently mis-allocate: flag for finance
        SecurityEvent.objects.create(kind='payment_allocation_mismatch', detail={'payment': str(p.pk), 'allocated': str(allocated), 'amount': str(p.amount)})
    for booking_id, amt in plan.items():
        booking = refresh_booking_status(Booking.objects.get(pk=booking_id), actor=p.payer)
        if booking.status == Booking.Status.CANCELLED:
            _refund_late_payment(p, booking, amt)
        elif booking_id in overpaid:
            _refund_overpayment(p, booking, overpaid[booking_id])
    order = CheckoutOrder.objects.select_for_update().get(pk=p.checkout_id)
    order.status = checkout_status(order)
    order.save(update_fields=['status', 'updated_at'])
    emit('payment.succeeded', p.pk, {'checkout': str(order.pk), 'kind': p.kind, 'amount': str(p.amount)})
    audit(p.payer, 'payment.succeeded', p, p.pk, after={'amount': str(p.amount)})
    return p, True


def _refund_late_payment(payment, booking, amount):
    """Money arrived for a booking that was already cancelled (its checkout expired while the customer was still paying).
    The seats may be gone, so don't revive it: request a full refund for finance to approve, and flag it."""
    refund = Refund.objects.create(booking=booking, amount=amount, tax_adjustment=Decimal('0.00'),
                                   reason='Paid after the checkout expired; seats had been released.', requested_by=None)
    SecurityEvent.objects.create(kind='payment_after_expiry', detail={'payment': str(payment.pk), 'booking': booking.reference,
                                                                     'amount': str(amount), 'refund': str(refund.pk)})
    emit('refund.requested', refund.pk, {'booking': str(booking.pk)})
    logger.warning('Payment %s arrived for cancelled booking %s; refund %s requested.', payment.pk, booking.reference, refund.pk)


def _refund_overpayment(payment, booking, amount):
    """A second order for the same balance was paid too. Keep the booking as it is and give the extra back."""
    refund = Refund.objects.create(booking=booking, amount=amount, tax_adjustment=Decimal('0.00'),
                                   reason='Paid twice for the same amount; the second payment is returned.', requested_by=None)
    SecurityEvent.objects.create(kind='payment_overpaid', detail={'payment': str(payment.pk), 'booking': booking.reference,
                                                                 'amount': str(amount), 'refund': str(refund.pk)})
    emit('refund.requested', refund.pk, {'booking': str(booking.pk)})
    logger.warning('Payment %s overpaid booking %s by %s; refund %s requested.', payment.pk, booking.reference, amount, refund.pk)


@transaction.atomic
def mark_failed(payment_id, reason='', raw=None):
    p = Payment.objects.select_for_update().get(pk=payment_id)
    if p.status in (Payment.Status.SUCCEEDED, Payment.Status.FAILED):   # never overwrite a success
        return p
    p.status, p.failure_reason = Payment.Status.FAILED, reason[:255]
    p.save()
    _txn(p, 'failed', Payment.Status.FAILED, raw)
    emit('payment.failed', p.pk, {'reason': reason})
    return p


def confirm_from_client(user, payment_id, razorpay_payment_id, razorpay_signature):
    """Called by the browser after Razorpay Checkout. We verify the signature ourselves; the browser's 'success' is not trusted."""
    p = Payment.objects.get(pk=payment_id, payer=user)
    if not p.gateway_order_id or not gateway.verify_checkout_signature(p.gateway_order_id, razorpay_payment_id, razorpay_signature):
        SecurityEvent.objects.create(kind='bad_checkout_signature', detail={'payment': str(p.pk)})
        raise BookingError('Payment could not be verified.', 'bad_signature')
    return mark_succeeded(p.pk, razorpay_payment_id)[0]


def record_manual_payment(actor, checkout, kind, amount, reference, booking_ids=None, request=None):
    """Staff record cash/bank payments; they sit PENDING_VERIFICATION until a second step approves them."""
    bookings = list(checkout.bookings.all())
    if booking_ids:
        bookings = [b for b in bookings if str(b.pk) in {str(i) for i in booking_ids}]
    due = amounts_due(bookings, kind)
    total = sum(due.values(), Decimal('0.00'))
    amount = Decimal(amount)
    if amount != total:
        raise BookingError(f'Amount must equal the amount due ({total}). Partial manual payments are entered per booking.', 'amount_mismatch')
    with transaction.atomic():
        p = Payment.objects.create(checkout=checkout, payer=checkout.user, kind=kind, method=Payment.Method.MANUAL, amount=amount,
                                   status=Payment.Status.PENDING_VERIFICATION, idempotency_key=f'manual:{checkout.pk}:{reference}',
                                   manual_reference=reference)
        _txn(p, 'created', Payment.Status.PENDING_VERIFICATION, raw={'plan': {str(k): str(v) for k, v in due.items()}, 'entered_by': str(actor.pk)})
        audit(actor, 'payment.manual_recorded', p, p.pk, after={'amount': str(amount), 'reference': reference}, request=request)
    return p


@transaction.atomic
def verify_manual_payment(actor, payment, approve, note='', request=None):
    # Lock and re-read: an approval and a rejection sent at the same moment must not both pass the pending check.
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.method != Payment.Method.MANUAL or payment.status != Payment.Status.PENDING_VERIFICATION:
        raise BookingError('Only pending manual payments can be verified.', 'not_pending')
    if payment.transactions.filter(raw__entered_by=str(actor.pk)).exists():
        raise BookingError('A different staff member must verify this payment.', 'self_verification')
    PaymentVerification.objects.create(payment=payment, verified_by=actor, approved=approve, note=note[:255])
    audit(actor, 'payment.manual_verified' if approve else 'payment.manual_rejected', payment, payment.pk, after={'note': note}, request=request)
    if approve:
        return mark_succeeded(payment.pk, raw={'verified_by': str(actor.pk)})[0]
    payment.status = Payment.Status.REJECTED
    payment.save(update_fields=['status', 'updated_at'])
    _txn(payment, 'rejected', Payment.Status.REJECTED)
    return payment


# ---------- webhooks: signature + duplicate protection ----------
def handle_webhook(raw_body: bytes, signature: str, payload: dict, ip=None):
    valid = gateway.verify_webhook_signature(raw_body, signature)
    event_id = payload.get('id') or payload.get('event_id') or ''
    if not valid:
        SecurityEvent.objects.create(kind='webhook_bad_signature', ip=ip)
        raise PermissionError('bad signature')
    if not event_id:
        raise ValueError('Razorpay webhook is missing its event id.')

    return _process_webhook_event(event_id, payload)


def retry_webhook_event(event_id):
    """Retry one previously authenticated webhook from the admin inbox."""
    with transaction.atomic():
        ev = PaymentGatewayEvent.objects.select_for_update().filter(
            provider='razorpay', event_id=event_id, signature_valid=True,
        ).first()
        if ev is None:
            raise BookingError('Webhook event not found.', 'not_found')
        if ev.processed_at:
            return 'duplicate'
        payload = ev.payload
    return _process_webhook_event(event_id, payload)


def _process_webhook_event(event_id, payload):
    processing_error = None
    with transaction.atomic():
        ev, _ = PaymentGatewayEvent.objects.select_for_update().get_or_create(
            provider='razorpay', event_id=event_id,
            defaults={
                'event_type': payload.get('event', ''),
                'payload': payload,
                'signature_valid': True,
            },
        )
        if ev.processed_at:
            return 'duplicate'

        # Keep the inbox row/error if dispatch fails, while rolling back any partial business
        # updates. A provider retry can then safely retry this same, already-authenticated event.
        try:
            with transaction.atomic():
                _dispatch(ev.payload)
        except Exception as exc:  # retryable: the outer transaction commits the error for observability
            ev.error = str(exc)[:300]
            ev.save(update_fields=['error'])
            logger.exception('webhook processing failed')
            processing_error = exc
        else:
            ev.error = ''
            ev.processed_at = timezone.now()
            ev.save(update_fields=['processed_at', 'error'])

    if processing_error:
        raise processing_error
    return 'processed'


def _captured_matches(payment, entity):
    """The captured amount and currency are the ones this order was created for (`order.paid` may carry no payment)."""
    if not entity or 'amount' not in entity:
        return True
    expected = int(payment.amount * 100)
    if int(entity['amount']) == expected and entity.get('currency', payment.currency) == payment.currency:
        return True
    SecurityEvent.objects.create(kind='payment_amount_mismatch', detail={
        'payment': str(payment.pk), 'expected_paise': expected, 'captured_paise': entity.get('amount'),
        'currency': entity.get('currency'),
    })
    logger.error('Payment %s captured %s %s, expected %s paise; not recorded.', payment.pk, entity.get('amount'),
                 entity.get('currency'), expected)
    return False


def _dispatch(payload):
    event = payload.get('event', '')
    ent = payload.get('payload', {})
    if event in ('payment.captured', 'order.paid'):
        pay = (ent.get('payment') or {}).get('entity', {})
        order_id = pay.get('order_id') or (ent.get('order') or {}).get('entity', {}).get('id')
        p = Payment.objects.filter(gateway_order_id=order_id).first()
        if p and _captured_matches(p, pay):
            fee = Decimal(pay.get('fee', 0)) / 100 if pay.get('fee') else None
            mark_succeeded(p.pk, pay.get('id'), raw=pay, fee=fee)
    elif event == 'payment.failed':
        pay = (ent.get('payment') or {}).get('entity', {})
        p = Payment.objects.filter(gateway_order_id=pay.get('order_id')).first()
        if p:
            mark_failed(p.pk, pay.get('error_description', ''), raw=pay)
    elif event in ('refund.processed', 'refund.failed'):
        ref = (ent.get('refund') or {}).get('entity', {})
        rt = RefundTransaction.objects.filter(gateway_refund_id=ref.get('id')).select_related('refund').first()
        if rt:
            with transaction.atomic():
                status = Refund.Status.PROCESSED if event == 'refund.processed' else Refund.Status.FAILED
                rt.status = status; rt.raw = ref; rt.save()
                rt.refund.status = status; rt.refund.save(update_fields=['status', 'updated_at'])
                emit('refund.' + status.lower(), rt.refund_id, {})


# ---------- refunds (processing is a separate transaction; the original payment is never edited) ----------
@transaction.atomic
def approve_refund(actor, refund: Refund, request=None):
    if refund.status != Refund.Status.REQUESTED:
        raise BookingError('Refund is not awaiting approval.', 'not_requested')
    refund.status, refund.approved_by = Refund.Status.APPROVED, actor
    refund.save()
    audit(actor, 'refund.approved', refund, refund.pk, after={'amount': str(refund.amount)}, request=request)
    emit('refund.approved', refund.pk, {})


@transaction.atomic
def reject_refund(actor, refund: Refund, reason, request=None):
    """Finance decides a requested refund is not owed (for example a duplicate request). The reason is kept."""
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status != Refund.Status.REQUESTED:
        raise BookingError('Only a refund awaiting approval can be rejected.', 'not_requested')
    reason = reason.strip()
    if not reason:
        raise BookingError('Give a reason for rejecting this refund.', 'reason_required')
    refund.status = Refund.Status.REJECTED
    refund.reason = f'{refund.reason} · Rejected: {reason}'.strip(' ·')[:255]
    refund.save(update_fields=['status', 'reason', 'updated_at'])
    audit(actor, 'refund.rejected', refund, refund.pk, after={'reason': reason}, request=request)
    return refund


def process_refund(refund_id):
    """Spreads the refund across the booking's successful gateway payments (latest first) and calls Razorpay per payment."""
    with transaction.atomic():
        r = Refund.objects.select_for_update().get(pk=refund_id)
        if r.status not in (Refund.Status.APPROVED, Refund.Status.FAILED):
            return r
        r.status = Refund.Status.PROCESSING
        r.save(update_fields=['status', 'updated_at'])
    remaining = r.amount
    allocs = (PaymentAllocation.objects.filter(booking=r.booking, payment__status=Payment.Status.SUCCEEDED, payment__method=Payment.Method.RAZORPAY)
              .select_related('payment').order_by('-created_at'))
    try:
        for a in allocs:
            if remaining <= 0:
                break
            already = sum((t.amount for t in a.payment.refund_transactions.exclude(status=Refund.Status.FAILED)), Decimal('0.00'))
            part = min(remaining, a.amount - already)
            if part <= 0 or not a.payment.gateway_payment_id:
                continue
            gid = gateway.create_refund(a.payment.gateway_payment_id, part, receipt=str(r.pk), notes={'refund': str(r.pk)})
            RefundTransaction.objects.create(refund=r, payment=a.payment, gateway_refund_id=gid, status=Refund.Status.PROCESSING, amount=part)
            remaining -= part
        if remaining > 0:
            raise gateway.GatewayError(f'Could not route {remaining} of the refund to gateway payments (manual payments must be refunded manually).')
    except gateway.GatewayError as exc:
        Refund.objects.filter(pk=r.pk).update(status=Refund.Status.FAILED)
        logger.warning('refund %s failed: %s', r.pk, exc)
        raise
    return r


# ---------- event refunds (paid back by hand over UPI; staff record the outcome) ----------
@transaction.atomic
def record_event_refund(actor, refund, *, sent, amount=None, upi_reference='', note='', request=None):
    """Close a due event refund as SENT (the customer is told on WhatsApp) or NOT_REFUNDED (e.g. the payment never arrived)."""
    from .models import EventRefund
    refund = EventRefund.objects.select_for_update().select_related('registration').get(pk=refund.pk)
    if refund.status != EventRefund.Status.DUE:
        raise BookingError('This refund has already been recorded.', 'not_due')
    upi_reference, note = (upi_reference or '').strip()[:40], (note or '').strip()[:255]
    if sent:
        try:
            amount = refund.amount if amount in (None, '') else Decimal(str(amount))
        except InvalidOperation:
            raise BookingError('Enter the amount you sent.', 'bad_amount')
        if not amount.is_finite() or not 0 < amount <= refund.registration.total_amount:
            raise BookingError(f'Enter an amount between ₹1 and the ₹{refund.registration.total_amount} paid.', 'bad_amount')
        refund.status, refund.amount = EventRefund.Status.SENT, amount
    else:
        if not note:
            raise BookingError('Say why no refund is being sent.', 'reason_required')
        refund.status = EventRefund.Status.NOT_REFUNDED
    refund.upi_reference, refund.note = upi_reference, note
    refund.recorded_by, refund.recorded_at = actor, timezone.now()
    refund.save()
    audit(actor, 'event_refund.recorded', refund, refund.pk,
          after={'status': refund.status, 'amount': str(refund.amount), 'upi_reference': upi_reference}, request=request)
    if sent:
        emit('event_booking.refund_sent', refund.registration_id, {'reference': refund.registration.reference})
    return refund
