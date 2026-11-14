"""Coupon rules, used by trip checkout, event bookings and the coupon previews. One implementation, server-side only.

A coupon takes money off the list price (price per participant × people) before GST is worked out, so tax is charged
on what the customer actually pays. A fixed-amount coupon is shared across the eligible trips in proportion to their
value, and the last trip absorbs the rounding so the parts add up exactly.

Scope: a coupon with no trips and no events works on everything. Otherwise it works only on the trips and events listed.
Its total-use limit counts trip checkouts and event bookings together.
"""
from decimal import Decimal

from django.utils import timezone

from core.money import percent_of, q


class CouponError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def find_coupon(code, *, lock=False):
    from crm.models import Coupon
    code = (code or '').strip().upper()
    if not code:
        raise CouponError('Enter a coupon code.')
    qs = Coupon.objects.select_for_update() if lock else Coupon.objects
    coupon = qs.filter(code__iexact=code).first()
    if coupon is None or not coupon.is_active:
        raise CouponError('This coupon code is not valid.')
    return coupon


def _event_uses(coupon):
    from trips.models import EventRegistration
    return EventRegistration.objects.filter(coupon=coupon).exclude(
        status__in=[EventRegistration.Status.CANCELLED, EventRegistration.Status.EXPIRED])


def coupon_uses(coupon):
    """Times the coupon has been used: trip checkouts plus event bookings that are still active."""
    from crm.models import CouponRedemption
    return CouponRedemption.objects.filter(coupon=coupon).count() + _event_uses(coupon).count()


def _check_common(coupon, now):
    if coupon.valid_from and now < coupon.valid_from:
        raise CouponError('This coupon is not active yet.')
    if coupon.valid_until and now > coupon.valid_until:
        raise CouponError('This coupon has expired.')
    if coupon.max_redemptions is not None and coupon_uses(coupon) >= coupon.max_redemptions:
        raise CouponError('This coupon has been fully used.')
    if not coupon.percent_basis_points and not coupon.fixed_amount:
        raise CouponError('This coupon is not valid.')


def check_coupon(coupon, user, now=None):
    """Raises CouponError if the coupon can't be used by this customer on a trip checkout right now."""
    from crm.models import CouponRedemption
    _check_common(coupon, now or timezone.now())
    if coupon.per_user_limit and CouponRedemption.objects.filter(coupon=coupon, user=user).count() >= coupon.per_user_limit:
        raise CouponError('You have already used this coupon.')


def check_event_coupon(coupon, event, phone=None, now=None):
    """Raises CouponError if the coupon can't be used for this event (by this phone number, when known)."""
    _check_common(coupon, now or timezone.now())
    events = set(coupon.events.values_list('pk', flat=True))
    if (events and event.pk not in events) or (not events and coupon.trips.exists()):
        raise CouponError('This coupon does not apply to this event.')
    if phone and coupon.per_user_limit and _event_uses(coupon).filter(contact_phone=phone).count() >= coupon.per_user_limit:
        raise CouponError('You have already used this coupon.')


def event_discount(coupon, amount):
    """Rupees off an event booking worth `amount` (never more than the amount)."""
    amount = q(amount)
    if coupon.percent_basis_points:
        return min(amount, percent_of(amount, coupon.percent_basis_points))
    return min(amount, q(coupon.fixed_amount))


def allocate_discount(coupon, lines):
    """
    `lines`: list of (key, trip_id, list_amount). Returns {key: discount}. Only trips the coupon covers get a discount;
    a discount never exceeds the line's amount.
    """
    allowed = set(coupon.trips.values_list('pk', flat=True))
    if not allowed and coupon.events.exists():
        raise CouponError('This coupon is for events only.')
    eligible = [(k, amt) for k, trip_id, amt in lines if not allowed or trip_id in allowed]
    if not eligible:
        raise CouponError('This coupon does not apply to the trips you selected.')
    out = {k: Decimal('0.00') for k, _, _ in lines}
    if coupon.percent_basis_points:
        for k, amt in eligible:
            out[k] = min(q(amt), percent_of(amt, coupon.percent_basis_points))
        return out
    base = sum((q(a) for _, a in eligible), Decimal('0.00'))
    remaining = min(q(coupon.fixed_amount), base)
    for i, (k, amt) in enumerate(eligible):
        share = remaining if i == len(eligible) - 1 else min(q(amt), q(q(coupon.fixed_amount) * q(amt) / base) if base else Decimal('0.00'))
        share = min(share, q(amt), remaining)
        out[k] = share
        remaining -= share
    return out
