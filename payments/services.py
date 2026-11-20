"""Payment orchestration. The browser is never trusted for payment status: success comes from a verified signature or webhook."""
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
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
    """Create (or replay) a Cashfree order covering one or several bookings of a trip checkout.

    A second request for the same amount (another tab, a retry after a failed attempt) gets the order that is still
    open instead of a new one, so the customer can't be charged twice for one balance. Should two orders settle anyway,
    `mark_succeeded` allocates only what is still due and requests a refund for the rest.
    """
    existing = _replay(user, idempotency_key)
    if existing:
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
    reusable = _open_payment_for(Payment.objects.filter(checkout=checkout), user, kind,
                                 lambda p: {k: str(v) for k, v in _plan(p).items()} == plan)
    if reusable:
        return reusable
    total = sum(due.values(), Decimal('0.00'))
    p = Payment.objects.create(checkout=checkout, payer=user, kind=kind, method=Payment.Method.CASHFREE, amount=total,
                               idempotency_key=idempotency_key)
    # stash the allocation plan so verification can allocate without trusting the client
    _txn(p, 'created', Payment.Status.CREATED, raw={'plan': plan})
    _open_gateway_order(p, user, booking_type='TRIP', reference=checkout.reference)
    return p


@transaction.atomic
def start_event_payment(user, registration, kind: str, idempotency_key: str):
    """Create (or replay) a Cashfree order for an event booking's advance (ADVANCE) or what is left (BALANCE / FULL)."""
    from trips.models import EventRegistration
    existing = _replay(user, idempotency_key)
    if existing:
        return existing
    reg = EventRegistration.objects.select_for_update().select_related('schedule__event').get(pk=registration.pk)
    if reg.registrant_id != user.pk:
        raise BookingError('This booking belongs to another account.', 'not_yours')
    if reg.effective_status not in (EventRegistration.Status.PENDING, EventRegistration.Status.CONFIRMED):
        raise BookingError('This booking is no longer active. Please book again from the event page.', 'not_active')
    if reg.schedule.has_started():
        raise BookingError('This event has started, so it can no longer be paid online.', 'started')
    paid = reg.paid_online()
    due = (max(Decimal('0.00'), reg.advance_amount - paid) if kind == PaymentKind.ADVANCE
           else max(Decimal('0.00'), reg.total_amount - paid))
    if due <= 0:
        raise BookingError('Nothing is due for this booking.', 'nothing_due')
    reusable = _open_payment_for(Payment.objects.filter(event_registration=reg), user, kind, lambda p: p.amount == due)
    if reusable:
        return reusable
    p = Payment.objects.create(event_registration=reg, payer=user, kind=kind, method=Payment.Method.CASHFREE, amount=due,
                               idempotency_key=idempotency_key)
    _txn(p, 'created', Payment.Status.CREATED, raw={'event_booking': str(reg.pk)})
    if reg.status == EventRegistration.Status.PENDING:
        # The places stay held while the customer pays, never past the event start.
        hold = timezone.now() + timedelta(minutes=checkout_hold_minutes())
        reg.reserved_until = min(max(reg.reserved_until or hold, hold), max(reg.schedule.starts_at, hold))
        reg.save(update_fields=['reserved_until', 'updated_at'])
    _open_gateway_order(p, user, booking_type='EVENT', reference=reg.reference)
    return p


def _replay(user, idempotency_key):
    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing and existing.payer_id != user.pk:
        raise BookingError('Idempotency key already used.', 'idempotency_conflict')
    return existing


def _open_payment_for(payments, user, kind, same_plan):
    """A Cashfree order opened within the hold time for exactly this amount, which the customer can still pay."""
    since = timezone.now() - timedelta(minutes=checkout_hold_minutes())
    candidates = (payments.filter(payer=user, kind=kind, method=Payment.Method.CASHFREE, status=Payment.Status.CREATED,
                                  created_at__gte=since).exclude(gateway_session_id='').order_by('-created_at'))
    return next((p for p in candidates if same_plan(p)), None)


def order_id_for(payment):
    """Our Cashfree order id. The prefix marks it as GoHyderabad's in the merchant account it shares with GoAdventure."""
    return f'{settings.CASHFREE_ORDER_PREFIX}-{payment.pk.hex[:24]}'


# Where Cashfree sends the customer after paying (or giving up): the website's thank-you page, which asks the server
# what happened (GET /payments/cashfree/verify/<order_id>/) and shows the booking, or how to try again.
RETURN_PATH = '/booking/thank-you'


def _open_gateway_order(p, user, *, booking_type, reference):
    """Create the Cashfree order for a new payment and keep its session id for the browser."""
    order_id = order_id_for(p)
    customer = {'customer_id': f'{settings.CASHFREE_ORDER_PREFIX}{user.pk}', 'customer_phone': gateway.customer_phone(user.phone_number)}
    if len(user.full_name or '') >= 3:
        customer['customer_name'] = user.full_name[:100]
    if user.email:
        customer['customer_email'] = user.email
    notify = settings.PUBLIC_API_ORIGIN
    order = gateway.create_order(
        order_id=order_id, order_amount=p.amount, customer=customer,
        return_url=f'{settings.FRONTEND_ORIGIN}{RETURN_PATH}?order_id={order_id}',
        # Cashfree only calls https addresses; locally the return page's verification records the payment instead.
        notify_url=f'{notify}/api/v1/payments/cashfree/webhook/' if notify.startswith('https://') else '',
        tags={'brand': settings.PAYMENT_BRAND, 'booking_type': booking_type, 'reference': reference, 'payment_kind': p.kind},
        note=f'{settings.PAYMENT_BRAND} {booking_type.lower()} {reference} ({p.kind.lower()})',
    )
    p.gateway_order_id, p.gateway_session_id = order_id, order['payment_session_id']
    p.save(update_fields=['gateway_order_id', 'gateway_session_id', 'updated_at'])
    _txn(p, 'gateway_order', Payment.Status.CREATED, raw={'cf_order_id': order.get('cf_order_id'), 'order_status': order.get('order_status')})


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
    if p.event_registration_id:
        _settle_event_payment(p)
        emit('payment.succeeded', p.pk, {'event_booking': str(p.event_registration_id), 'kind': p.kind, 'amount': str(p.amount)})
        audit(p.payer, 'payment.succeeded', p, p.pk, after={'amount': str(p.amount)})
        return p, True
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


def _settle_event_payment(p):
    """A verified payment for an event booking: confirm it once the advance is in, and give back anything not owed."""
    from trips.models import EventRegistration
    reg = EventRegistration.objects.select_for_update().get(pk=p.event_registration_id)
    paid_before = reg.paid_online() - p.amount        # this payment is already SUCCEEDED
    if reg.effective_status in (EventRegistration.Status.CANCELLED, EventRegistration.Status.EXPIRED):
        _refund_event_payment(p, reg, p.amount, 'Paid after the booking was cancelled or its hold ran out; places had been released.',
                              'payment_after_expiry')
        return
    owed = max(Decimal('0.00'), reg.total_amount - paid_before)
    if p.amount > owed:
        _refund_event_payment(p, reg, p.amount - owed, 'Paid twice for the same amount; the extra is returned.', 'payment_overpaid')
    if reg.status == EventRegistration.Status.PENDING and reg.paid_online() >= reg.advance_amount:
        reg.status = EventRegistration.Status.CONFIRMED   # save() sends the customer the confirmation message
        reg.save()


def _refund_event_payment(payment, reg, amount, reason, kind):
    refund = Refund.objects.create(event_registration=reg, amount=amount, tax_adjustment=Decimal('0.00'), reason=reason[:255],
                                   requested_by=None)
    SecurityEvent.objects.create(kind=kind, detail={'payment': str(payment.pk), 'event_booking': reg.reference,
                                                    'amount': str(amount), 'refund': str(refund.pk)})
    emit('refund.requested', refund.pk, {'event_booking': str(reg.pk)})
    logger.warning('Payment %s for event booking %s: %s Refund %s of %s requested.', payment.pk, reg.reference, reason, refund.pk, amount)


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


# ---------- verification: Cashfree is asked, the browser is never trusted ----------
# What the customer is told after returning from Cashfree, from the order's attempts.
OUTCOMES = {'SUCCESS': 'paid', 'FAILED': 'failed', 'USER_DROPPED': 'cancelled', 'CANCELLED': 'cancelled', 'VOID': 'failed',
            'PENDING': 'pending', 'NOT_ATTEMPTED': 'pending'}


def reconcile_order(order_id):
    """Ask Cashfree what happened to one of our orders and record it.

    Returns (payment, outcome) with outcome one of paid | pending | failed | cancelled | expired, or (None, None) for an
    order that isn't ours (the merchant account is shared with GoAdventure). Only a SUCCESS for this order's exact amount
    and currency records the payment; anything else leaves the order open so the customer can try again.
    """
    p = Payment.objects.filter(gateway_order_id=order_id, method=Payment.Method.CASHFREE).first()
    if p is None:
        return None, None
    if p.status == Payment.Status.SUCCEEDED:
        return p, 'paid'
    if p.status == Payment.Status.FAILED:
        return p, 'expired'
    attempts = sorted(gateway.get_order_payments(order_id), key=lambda a: str(a.get('payment_time') or ''))
    success = next((a for a in attempts if a.get('payment_status') == 'SUCCESS'), None)
    if success:
        if not _amount_matches(p, success):
            return p, 'pending'   # held for finance: a security event says why
        p, _ = mark_succeeded(p.pk, str(success.get('cf_payment_id') or ''), raw=_attempt_summary(success))
        return p, 'paid'
    order = gateway.get_order(order_id)
    if order.get('order_status') in ('EXPIRED', 'TERMINATED'):
        return mark_failed(p.pk, 'The payment window closed without a payment.', raw={'order_status': order.get('order_status')}), 'expired'
    last = attempts[-1] if attempts else None
    if last and last.get('payment_message'):
        Payment.objects.filter(pk=p.pk).update(failure_reason=str(last['payment_message'])[:255])
    return p, OUTCOMES.get((last or {}).get('payment_status'), 'pending')


def _attempt_summary(attempt):
    """The parts of a Cashfree payment worth keeping (no card or bank account details)."""
    keep = ('cf_payment_id', 'payment_status', 'payment_amount', 'payment_currency', 'payment_group', 'payment_time',
            'payment_completion_time', 'bank_reference', 'payment_message')
    return {k: attempt.get(k) for k in keep if attempt.get(k) is not None}


def _amount_matches(payment, attempt):
    """The amount and currency paid are the ones this order was created for."""
    try:
        paid = Decimal(str(attempt.get('payment_amount'))).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        paid = None
    if paid == payment.amount and attempt.get('payment_currency', 'INR') == payment.currency:
        return True
    SecurityEvent.objects.create(kind='payment_amount_mismatch', detail={
        'payment': str(payment.pk), 'expected': str(payment.amount), 'paid': str(attempt.get('payment_amount')),
        'currency': attempt.get('payment_currency'),
    })
    logger.error('Payment %s: Cashfree reports %s %s, expected %s; not recorded.', payment.pk, attempt.get('payment_amount'),
                 attempt.get('payment_currency'), payment.amount)
    return False


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
PROVIDER = 'cashfree'


def webhook_event_id(payload, idempotency_key=''):
    """One key per real-world event, so a redelivery is recognised: Cashfree's idempotency header when it sends one,
    otherwise the event type, the payment or refund and its status."""
    if idempotency_key:
        return idempotency_key[:100]
    data = payload.get('data') or {}
    pay, ref = data.get('payment') or {}, data.get('refund') or {}
    return ':'.join([str(payload.get('type', '')), str(pay.get('cf_payment_id') or ref.get('cf_refund_id') or ref.get('refund_id') or ''),
                     str(pay.get('payment_status') or ref.get('refund_status') or '')])[:100]


def handle_webhook(raw_body: bytes, timestamp: str, signature: str, payload: dict, idempotency_key='', ip=None):
    if not gateway.verify_webhook_signature(raw_body, timestamp, signature):
        SecurityEvent.objects.create(kind='webhook_bad_signature', ip=ip)
        raise PermissionError('bad signature')
    return _process_webhook_event(webhook_event_id(payload, idempotency_key), payload)


def retry_webhook_event(event_id):
    """Retry one previously authenticated webhook from the admin inbox."""
    with transaction.atomic():
        ev = PaymentGatewayEvent.objects.select_for_update().filter(
            provider=PROVIDER, event_id=event_id, signature_valid=True,
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
            provider=PROVIDER, event_id=event_id,
            defaults={'event_type': str(payload.get('type', ''))[:80], 'payload': payload, 'signature_valid': True},
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


def _dispatch(payload):
    """The notification only says which order or refund changed; what happened is read back from Cashfree."""
    event_type = str(payload.get('type', ''))
    data = payload.get('data') or {}
    if event_type.startswith('PAYMENT_'):
        order_id = (data.get('order') or {}).get('order_id')
        if order_id:
            reconcile_order(order_id)   # orders that aren't ours (GoAdventure's) are ignored
    elif event_type.startswith('REFUND_'):
        refund_id = (data.get('refund') or {}).get('refund_id')
        if refund_id:
            reconcile_refund(refund_id)


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


# Cashfree refund status -> ours (a refund can sit PENDING / ONHOLD for days before the bank completes it).
REFUND_STATUS = {'SUCCESS': Refund.Status.PROCESSED, 'CANCELLED': Refund.Status.FAILED, 'REJECTED': Refund.Status.FAILED,
                 'PENDING': Refund.Status.PROCESSING, 'ONHOLD': Refund.Status.PROCESSING, 'PENDING_APPROVAL': Refund.Status.PROCESSING}


def _refundable_payments(r):
    """(payment, the part of it that belongs to this refund's booking), latest first: only Cashfree payments refund online."""
    online = {'status': Payment.Status.SUCCEEDED, 'method': Payment.Method.CASHFREE}
    if r.booking_id:
        allocs = (PaymentAllocation.objects.filter(booking=r.booking, **{f'payment__{k}': v for k, v in online.items()})
                  .select_related('payment').order_by('-created_at'))
        return [(a.payment, a.amount) for a in allocs]
    return [(p, p.amount) for p in Payment.objects.filter(event_registration=r.event_registration, **online).order_by('-created_at')]


def process_refund(refund_id):
    """Spreads an approved refund across the booking's Cashfree payments (latest first), one Cashfree refund per payment.

    Each Cashfree refund has our own id, so a retry after a timeout can't refund the same money twice.
    """
    with transaction.atomic():
        r = Refund.objects.select_for_update().get(pk=refund_id)
        if r.status not in (Refund.Status.APPROVED, Refund.Status.FAILED):
            return r
        r.status = Refund.Status.PROCESSING
        r.save(update_fields=['status', 'updated_at'])
    remaining = r.amount - sum((t.amount for t in r.transactions.exclude(status=Refund.Status.FAILED)), Decimal('0.00'))
    try:
        for payment, share in _refundable_payments(r):
            if remaining <= 0:
                break
            already = sum((t.amount for t in payment.refund_transactions.exclude(status=Refund.Status.FAILED)), Decimal('0.00'))
            part = min(remaining, share - already)
            if part <= 0 or not payment.gateway_order_id:
                continue
            refund_id_ = f'{settings.CASHFREE_ORDER_PREFIX}-R-{r.pk.hex[:12]}-{r.transactions.count() + 1}'
            result = gateway.create_refund(order_id=payment.gateway_order_id, refund_id=refund_id_, refund_amount=part,
                                           note=(r.reason or 'GoHyderabad refund'))
            RefundTransaction.objects.create(refund=r, payment=payment, gateway_refund_id=refund_id_, amount=part,
                                             status=REFUND_STATUS.get(result.get('refund_status'), Refund.Status.PROCESSING),
                                             raw={k: result.get(k) for k in ('cf_refund_id', 'refund_status', 'refund_arn', 'status_description')})
            remaining -= part
        if remaining > 0:
            raise gateway.GatewayError(f'Could not route {remaining} of the refund to online payments (cash or bank payments are refunded by hand).')
    except gateway.GatewayError as exc:
        Refund.objects.filter(pk=r.pk).update(status=Refund.Status.FAILED)
        logger.warning('refund %s failed: %s', r.pk, exc)
        raise
    _settle_refund(r.pk)
    return Refund.objects.get(pk=r.pk)


def reconcile_refund(gateway_refund_id):
    """Read one Cashfree refund's status back (after its webhook, or on the periodic check) and record it."""
    rt = RefundTransaction.objects.select_related('payment').filter(gateway_refund_id=gateway_refund_id).first()
    if rt is None or rt.payment is None:
        return None   # not ours
    result = gateway.get_refund(rt.payment.gateway_order_id, gateway_refund_id)
    status = REFUND_STATUS.get(result.get('refund_status'), Refund.Status.PROCESSING)
    if status != rt.status:
        rt.status = status
        rt.raw = {**(rt.raw or {}), **{k: result.get(k) for k in ('refund_status', 'refund_arn', 'status_description', 'processed_at')}}
        rt.save(update_fields=['status', 'raw'])
    _settle_refund(rt.refund_id)
    return rt


@transaction.atomic
def _settle_refund(refund_pk):
    """A refund is done when every Cashfree part succeeded, and failed when any part failed (finance can retry it)."""
    r = Refund.objects.select_for_update().get(pk=refund_pk)
    parts = list(r.transactions.all())
    if not parts or r.status in (Refund.Status.PROCESSED, Refund.Status.REJECTED):
        return r
    if any(t.status == Refund.Status.FAILED for t in parts):
        new = Refund.Status.FAILED
    elif sum((t.amount for t in parts), Decimal('0.00')) >= r.amount and all(t.status == Refund.Status.PROCESSED for t in parts):
        new = Refund.Status.PROCESSED
    else:
        new = Refund.Status.PROCESSING
    if new != r.status:
        r.status = new
        r.save(update_fields=['status', 'updated_at'])
        if new in (Refund.Status.PROCESSED, Refund.Status.FAILED):
            emit('refund.' + new.lower(), r.pk, {})
    return r


def refundable_amount(*, booking=None, event_registration=None):
    """Paid online for this booking and not already being refunded."""
    if booking is not None:
        paid = (PaymentAllocation.objects.filter(booking=booking, payment__status=Payment.Status.SUCCEEDED,
                                                 payment__method=Payment.Method.CASHFREE).aggregate(t=Sum('amount'))['t'])
        refunds = Refund.objects.filter(booking=booking)
    else:
        paid = (Payment.objects.filter(event_registration=event_registration, status=Payment.Status.SUCCEEDED,
                                       method=Payment.Method.CASHFREE).aggregate(t=Sum('amount'))['t'])
        refunds = Refund.objects.filter(event_registration=event_registration)
    taken = refunds.exclude(status__in=(Refund.Status.REJECTED, Refund.Status.FAILED)).aggregate(t=Sum('amount'))['t']
    return max(Decimal('0.00'), (paid or Decimal('0.00')) - (taken or Decimal('0.00')))


@transaction.atomic
def issue_refund(actor, *, amount, reason, booking=None, event_registration=None, request=None):
    """Finance returns all or part of an online payment directly (goodwill, a price change), outside a cancellation.
    It is approved by the person issuing it and sent to Cashfree straight away."""
    try:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        raise BookingError('Enter the amount to refund.', 'bad_amount')
    reason = (reason or '').strip()
    if not reason:
        raise BookingError('Say why this refund is given; the customer may ask.', 'reason_required')
    available = refundable_amount(booking=booking, event_registration=event_registration)
    if not 0 < amount <= available:
        raise BookingError(f'Enter an amount between ₹1 and ₹{available}, the online payment not yet refunded.', 'bad_amount')
    refund = Refund.objects.create(booking=booking, event_registration=event_registration, amount=amount,
                                   tax_adjustment=Decimal('0.00'), reason=reason[:255], requested_by=actor,
                                   approved_by=actor, status=Refund.Status.APPROVED)
    audit(actor, 'refund.issued', refund, refund.pk, after={'amount': str(amount), 'reason': reason}, request=request)
    emit('refund.approved', refund.pk, {})
    return refund


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
