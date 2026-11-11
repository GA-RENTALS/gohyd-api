"""
Booking domain logic. Everything money- or capacity-related runs here, server-side, inside transactions.

Capacity: seats are committed when the booking rows are created (no separate temporary hold), under a row lock on each
TripSchedule, and the whole checkout is all-or-nothing (section 3.3).
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from core.money import AdvanceSplit, add_gst, extract_gst, percent_of, q, split_advance
from core.services import audit, emit, get_setting
from payments.models import GstConfiguration, Payment, PaymentAllocation
from trips.models import Trip, TripSchedule

from .models import (Booking, BookingCancellation, BookingItem, BookingSeatAllocation, BookingStatusHistory, CheckoutItem,
                     CheckoutOrder)


class BookingError(Exception):
    """A clear, user-presentable reason a checkout/booking action can't proceed."""
    def __init__(self, message, code='booking_error', details=None):
        super().__init__(message)
        self.message, self.code, self.details = message, code, details or {}


# ---------- effective settings: schedule override -> trip override -> global ----------
def effective_advance_bp(schedule: TripSchedule) -> int:
    for v in (schedule.advance_basis_points, schedule.trip.advance_basis_points):
        if v is not None:
            return int(v)
    return int(get_setting('advance.default_basis_points'))


def effective_balance_days(schedule: TripSchedule) -> int:
    for v in (schedule.balance_due_days_before, schedule.trip.balance_due_days_before):
        if v is not None:
            return int(v)
    return int(get_setting('balance.default_due_days_before'))


def gst_for(trip: Trip):
    if trip.gst_configuration_id:
        return trip.gst_configuration
    return GstConfiguration.objects.filter(is_default=True, effective_from__lte=timezone.now()).order_by('-effective_from').first()


@dataclass
class Pricing:
    unit_price: Decimal
    subtotal: Decimal       # net of tax
    tax: Decimal
    total: Decimal          # what the customer pays
    split: AdvanceSplit
    advance_bp: int
    balance_due_at: object
    tax_snapshot: dict


def price(schedule: TripSchedule, participants: int, now=None, discount=Decimal('0.00')) -> Pricing:
    """`discount` (from a coupon) comes off the list amount before GST, so tax is charged on what is actually paid."""
    now = now or timezone.now()
    unit = q(schedule.price_per_participant)
    gross_or_net = max(q(unit * participants) - q(discount), Decimal('0.00'))
    cfg = gst_for(schedule.trip)
    if cfg and cfg.enabled:
        t = extract_gst(gross_or_net, cfg.rate_basis_points) if cfg.price_includes_tax else add_gst(gross_or_net, cfg.rate_basis_points)
        snap = cfg.snapshot()
    else:
        from core.money import Tax
        t, snap = Tax(net=gross_or_net, tax=Decimal('0.00'), gross=gross_or_net), {'enabled': False}
    bp = effective_advance_bp(schedule)
    due = schedule.starts_at - timedelta(days=effective_balance_days(schedule))
    return Pricing(unit, t.net, t.tax, t.gross, split_advance(t.gross, bp), bp, due, snap)


def _log(booking, to, actor=None, note=''):
    BookingStatusHistory.objects.create(booking=booking, from_status=booking.status if booking.pk and booking.status != to else '',
                                        to_status=to, actor=actor, note=note)


# ---------- checkout: multi-trip, all-or-nothing ----------
@dataclass
class CheckoutLine:
    schedule_id: object
    participant_count: int
    pickup_point_id: object = None


@transaction.atomic
def create_checkout(user, lines, idempotency_key, request=None, coupon_code=None):
    """
    Validates capacity for EVERY line before committing anything. If any line can't be fulfilled, raises BookingError
    listing the failures and nothing is created. Replaying the same idempotency_key returns the original checkout.
    """
    existing = CheckoutOrder.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.user_id != user.pk:
            raise BookingError('Idempotency key already used.', 'idempotency_conflict')
        return existing
    if not lines:
        raise BookingError('Your checkout has no trips.', 'empty_checkout')

    # one booking per schedule per checkout; lock in a stable order to avoid deadlocks
    ids = sorted({str(l.schedule_id) for l in lines})
    if len(ids) != len(lines):
        raise BookingError('Each trip date can appear only once per checkout.', 'duplicate_line')
    schedules = {str(s.pk): s for s in TripSchedule.objects.select_for_update().select_related('trip').filter(pk__in=ids).order_by('pk')}

    failures, now = [], timezone.now()
    for l in lines:
        s = schedules.get(str(l.schedule_id))
        if not s:
            failures.append({'schedule': str(l.schedule_id), 'reason': 'not_found'}); continue
        if not s.is_open or s.trip.operational_status != Trip.Operational.OPEN or s.trip.status != 'PUBLISHED':
            failures.append({'schedule': str(s.pk), 'reason': 'unavailable'})
        elif s.starts_at <= now:
            failures.append({'schedule': str(s.pk), 'reason': 'already_departed'})
        elif l.participant_count < 1:
            failures.append({'schedule': str(s.pk), 'reason': 'invalid_participant_count'})
        elif s.seats_left < l.participant_count:
            failures.append({'schedule': str(s.pk), 'reason': 'insufficient_seats', 'seats_left': s.seats_left})
    if failures:
        raise BookingError('Some trips in your checkout cannot be booked. Nothing has been charged or reserved.', 'checkout_unavailable', {'items': failures})

    coupon, discounts = None, {}
    if coupon_code:
        from .coupons import CouponError, allocate_discount, check_coupon, find_coupon
        try:
            coupon = find_coupon(coupon_code, lock=True)      # row lock: two checkouts can't both take the last use
            check_coupon(coupon, user, now)
            discounts = allocate_discount(coupon, [
                (str(l.schedule_id), schedules[str(l.schedule_id)].trip_id,
                 q(schedules[str(l.schedule_id)].price_per_participant) * l.participant_count) for l in lines])
        except CouponError as e:
            raise BookingError(e.message, 'invalid_coupon')
    priced = {str(l.schedule_id): price(schedules[str(l.schedule_id)], l.participant_count, now,
                                         discounts.get(str(l.schedule_id), Decimal('0.00'))) for l in lines}
    discount_total = sum(discounts.values(), Decimal('0.00'))
    order = CheckoutOrder.objects.create(
        user=user, idempotency_key=idempotency_key, coupon=coupon, discount_total=discount_total,
        total_amount=sum((p.total for p in priced.values()), Decimal('0.00')),
        advance_total=sum((p.split.advance for p in priced.values()), Decimal('0.00')))
    if coupon:
        from crm.models import CouponRedemption
        CouponRedemption.objects.create(coupon=coupon, user=user, checkout=order, discount=discount_total)

    for l in lines:
        s, p = schedules[str(l.schedule_id)], priced[str(l.schedule_id)]
        item = CheckoutItem.objects.create(checkout=order, schedule=s, participant_count=l.participant_count,
                                           pickup_point_id=l.pickup_point_id, advance_basis_points=p.advance_bp)
        booking = Booking.objects.create(
            checkout=order, checkout_item=item, primary_booker=user, schedule=s, participant_count=l.participant_count,
            unit_price=p.unit_price, discount_amount=discounts.get(str(s.pk), Decimal('0.00')),
            subtotal=p.subtotal, tax_amount=p.tax, total_amount=p.total,
            advance_basis_points=p.advance_bp, advance_amount=p.split.advance, balance_amount=p.split.balance,
            balance_due_at=p.balance_due_at, tax_snapshot=p.tax_snapshot, pickup_point_id=l.pickup_point_id,
            refund_policy_snapshot=[{'days_before': x.days_before, 'refund_basis_points': x.refund_basis_points}
                                    for x in s.trip.policies.all()])
        BookingItem.objects.create(booking=booking, description=f'{s.trip.slug} × {l.participant_count}',
                                   quantity=l.participant_count, unit_amount=p.unit_price)
        BookingSeatAllocation.objects.create(booking=booking, schedule=s, seats=l.participant_count)
        TripSchedule.objects.filter(pk=s.pk).update(seats_booked=F('seats_booked') + l.participant_count)
        _log(booking, Booking.Status.PENDING_ADVANCE, user)
        emit('booking.created', booking.pk, {'reference': booking.reference})
    audit(user, 'checkout.create', order, order.pk, after={'total': str(order.total_amount)}, request=request)
    return order


# ---------- payments -> booking state ----------
def paid_amount(booking, kind=None):
    qs = PaymentAllocation.objects.filter(booking=booking, payment__status=Payment.Status.SUCCEEDED)
    if kind:
        qs = qs.filter(kind=kind)
    return qs.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')


def refunded_amount(booking):
    from payments.models import Refund
    return (Refund.objects.filter(booking=booking, status__in=[Refund.Status.PROCESSED, Refund.Status.PROCESSING, Refund.Status.APPROVED])
            .aggregate(t=Sum('amount'))['t'] or Decimal('0.00'))


def outstanding(booking):
    if booking.status == Booking.Status.CANCELLED:
        return Decimal('0.00')
    return max(Decimal('0.00'), booking.total_amount - paid_amount(booking))


def refresh_booking_status(booking, actor=None):
    """Recompute status from successful allocations. Idempotent."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status in (Booking.Status.CANCELLED, Booking.Status.COMPLETED, Booking.Status.NO_SHOW):
        return booking
    paid = paid_amount(booking)
    if paid >= booking.total_amount:
        new = Booking.Status.FULLY_PAID
    elif paid >= booking.advance_amount:
        new = Booking.Status.CONFIRMED
    else:
        new = Booking.Status.PENDING_ADVANCE
    if new != booking.status:
        _log(booking, new, actor)
        booking.status = new
        booking.save(update_fields=['status', 'updated_at'])
        if new == Booking.Status.CONFIRMED:
            emit('booking.confirmed', booking.pk, {'reference': booking.reference})
        if new == Booking.Status.FULLY_PAID:
            emit('invoice.generate', booking.pk, {})
    return booking


def checkout_status(order):
    bookings = list(order.bookings.exclude(status=Booking.Status.CANCELLED))
    if not bookings:
        return CheckoutOrder.Status.CANCELLED
    if all(b.status == Booking.Status.FULLY_PAID for b in bookings):
        return CheckoutOrder.Status.PAID
    if any(paid_amount(b) > 0 for b in bookings):
        return CheckoutOrder.Status.PARTIALLY_PAID
    return CheckoutOrder.Status.PENDING


# ---------- cancellation & refunds: independent per booking ----------
def refund_percent_for(booking, now=None):
    now = now or timezone.now()
    days = (booking.schedule.starts_at - now).total_seconds() / 86400
    tiers = sorted(booking.refund_policy_snapshot, key=lambda t: -t['days_before'])
    for t in tiers:
        if days >= t['days_before']:
            return int(t['refund_basis_points'])
    return 0


@transaction.atomic
def cancel_booking(booking, actor, reason='', request=None):
    """Cancels ONE booking, releases its seats, and requests a refund per its policy snapshot. Others in the checkout are untouched."""
    from payments.models import Refund
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    if booking.status == Booking.Status.CANCELLED:
        return booking
    if booking.status in (Booking.Status.COMPLETED, Booking.Status.NO_SHOW):
        raise BookingError('This booking can no longer be cancelled.', 'not_cancellable')
    paid = paid_amount(booking) - refunded_amount(booking)
    bp = refund_percent_for(booking)
    refund_amount = min(percent_of(paid, bp), paid) if paid > 0 else Decimal('0.00')
    for alloc in booking.seat_allocations.select_for_update().filter(released_at__isnull=True):
        TripSchedule.objects.filter(pk=alloc.schedule_id).update(seats_booked=F('seats_booked') - alloc.seats)
        alloc.released_at = timezone.now(); alloc.save(update_fields=['released_at'])
    _log(booking, Booking.Status.CANCELLED, actor, reason)
    booking.status = Booking.Status.CANCELLED
    booking.save(update_fields=['status', 'updated_at'])
    BookingCancellation.objects.create(booking=booking, requested_by=actor, reason=reason[:255], refund_basis_points=bp, refund_amount=refund_amount)
    if refund_amount > 0:
        tax_part = percent_of(refund_amount, int(booking.tax_amount * 10000 / booking.total_amount)) if booking.total_amount else Decimal('0.00')
        r = Refund.objects.create(booking=booking, amount=refund_amount, tax_adjustment=tax_part, reason=reason[:255], requested_by=actor)
        emit('refund.requested', r.pk, {'booking': str(booking.pk)})
    audit(actor, 'booking.cancel', booking, booking.pk, after={'refund': str(refund_amount), 'bp': bp}, request=request)
    emit('booking.cancelled', booking.pk, {'reference': booking.reference})
    return booking


# ---------- departure clearance (3.2) ----------
def can_depart(booking) -> bool:
    return booking.status == Booking.Status.FULLY_PAID or outstanding(booking) == 0 or bool(booking.departure_exception_by_id)


@transaction.atomic
def grant_departure_exception(booking, actor, reason, request=None):
    if not actor.has_perm('bookings.grant_departure_exception'):
        raise BookingError('You are not authorised to grant departure exceptions.', 'forbidden')
    if not reason.strip():
        raise BookingError('A reason is required.', 'reason_required')
    booking.departure_exception_by, booking.departure_exception_reason = actor, reason[:255]
    booking.departure_exception_at = timezone.now()
    booking.save(update_fields=['departure_exception_by', 'departure_exception_reason', 'departure_exception_at'])
    audit(actor, 'booking.departure_exception', booking, booking.pk, after={'reason': reason, 'outstanding': str(outstanding(booking))}, request=request)
