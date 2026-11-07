"""
Money rules (sections 3.1, 3.5, 14): NUMERIC(12,2) in the database, Decimal in code, one rounding rule
(ROUND_HALF_UP to 2 places) everywhere, and every calculation done server-side. Percentages are basis points
(30% == 3000) so they are exact integers.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal('0.01')


def q(value) -> Decimal:
    """Quantise to paise with the platform's single rounding rule."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def percent_of(amount, basis_points: int) -> Decimal:
    if not 0 <= int(basis_points) <= 10000:
        raise ValueError('basis_points must be between 0 and 10000')
    return q(Decimal(amount) * int(basis_points) / Decimal(10000))


@dataclass(frozen=True)
class AdvanceSplit:
    total: Decimal
    advance: Decimal
    balance: Decimal


def split_advance(total, advance_basis_points: int) -> AdvanceSplit:
    """advance = round(total * pct); balance = total - advance, so the parts always sum exactly to total."""
    total = q(total)
    advance = percent_of(total, advance_basis_points)
    return AdvanceSplit(total=total, advance=advance, balance=total - advance)


@dataclass(frozen=True)
class Tax:
    net: Decimal
    tax: Decimal
    gross: Decimal


def add_gst(net, rate_basis_points: int) -> Tax:
    """Tax-exclusive price -> net / tax / gross."""
    net = q(net)
    tax = percent_of(net, rate_basis_points)
    return Tax(net=net, tax=tax, gross=net + tax)


def extract_gst(gross, rate_basis_points: int) -> Tax:
    """Tax-inclusive price -> net / tax / gross, with net + tax == gross exactly."""
    gross = q(gross)
    net = q(gross * 10000 / Decimal(10000 + int(rate_basis_points)))
    return Tax(net=net, tax=gross - net, gross=gross)


def format_inr(amount) -> str:
    """Decimal('123456.5') -> '₹1,23,456.50' (Indian digit grouping)."""
    if amount is None:
        return '—'
    amount = q(amount)
    sign = '-' if amount < 0 else ''
    rupees, paise = divmod(int(abs(amount) * 100), 100)
    digits = str(rupees)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ','.join(groups + [tail])
    return f'{sign}₹{digits}' + (f'.{paise:02d}' if paise else '')
