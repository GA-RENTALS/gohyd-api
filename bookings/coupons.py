"""Coupon rules, used by checkout creation and the coupon preview. One implementation, server-side only.

A coupon takes money off the list price (price per participant × people) before GST is worked out, so tax is charged
on what the customer actually pays. A fixed-amount coupon is shared across the eligible trips in proportion to their
value, and the last trip absorbs the rounding so the parts add up exactly.
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


def check_coupon(coupon, user, now=None):
    """Raises CouponError if the coupon can't be used by this customer right now."""
    from crm.models import CouponRedemption
    now = now or timezone.now()
    if coupon.valid_from and now < coupon.valid_from:
        raise CouponError('This coupon is not active yet.')
    if coupon.valid_until and now > coupon.valid_until:
        raise CouponError('This coupon has expired.')
    if coupon.max_redemptions is not None and CouponRedemption.objects.filter(coupon=coupon).count() >= coupon.max_redemptions:
        raise CouponError('This coupon has been fully used.')
    if coupon.per_user_limit and CouponRedemption.objects.filter(coupon=coupon, user=user).count() >= coupon.per_user_limit:
        raise CouponError('You have already used this coupon.')
    if not coupon.percent_basis_points and not coupon.fixed_amount:
        raise CouponError('This coupon is not valid.')


def allocate_discount(coupon, lines):
    """
    `lines`: list of (key, trip_id, list_amount). Returns {key: discount}. Only trips the coupon covers get a discount;
    a discount never exceeds the line's amount.
    """
    allowed = set(coupon.trips.values_list('pk', flat=True))
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
