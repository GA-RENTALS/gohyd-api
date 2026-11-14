"""Shared building blocks for the staff list pages (bookings, payments, customers, marketing, team).

Every list endpoint returns ready-to-show rows (names, titles, money as strings) plus page numbers, and can export the
same filtered rows as CSV. Keeping these helpers in one place means every page paginates, filters by date and exports
the same way.
"""
import csv
from collections import defaultdict
from datetime import date, datetime, time

from django.core.paginator import EmptyPage, Paginator
from django.db.models import F, Func, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from bookings.models import Booking
from payments.models import Payment, PaymentAllocation
from trips.models import EventRegistration

from .overview import ZERO, _iso, _money

PAGE_SIZE = 25
EXPORT_LIMIT = 10_000

TRIP_AWAITING = [Booking.Status.PENDING_ADVANCE, Booking.Status.CONFIRMED]
TRIP_PAID = [Booking.Status.FULLY_PAID, Booking.Status.COMPLETED]
TRIP_CANCELLED = [Booking.Status.CANCELLED, Booking.Status.NO_SHOW]


# ---------- pagination, dates, export ----------

def paginate(request, qs, size=PAGE_SIZE):
    """(page, meta) for ?page=N. Out-of-range pages land on the last page instead of failing."""
    paginator = Paginator(qs, size)
    try:
        number = max(1, int(request.query_params.get('page', 1)))
    except ValueError:
        number = 1
    try:
        page = paginator.page(number)
    except EmptyPage:
        page = paginator.page(paginator.num_pages or 1)
    return page, {'count': paginator.count, 'page': page.number, 'pages': paginator.num_pages or 1}


def _parse_day(value, name):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({name: 'Use a date like 2026-11-30.'})


def date_range(request):
    """Aware datetimes for ?from=YYYY-MM-DD&to=YYYY-MM-DD (both days included). Either side may be missing."""
    tz = timezone.get_current_timezone()
    raw_from, raw_to = request.query_params.get('from', '').strip(), request.query_params.get('to', '').strip()
    start = timezone.make_aware(datetime.combine(_parse_day(raw_from, 'from'), time.min), tz) if raw_from else None
    end = timezone.make_aware(datetime.combine(_parse_day(raw_to, 'to'), time.max), tz) if raw_to else None
    if start and end and start > end:
        raise ValidationError({'to': 'The end date is before the start date.'})
    return start, end


def in_range(qs, field, start, end):
    if start:
        qs = qs.filter(**{f'{field}__gte': start})
    if end:
        qs = qs.filter(**{f'{field}__lte': end})
    return qs


def wants_export(request):
    return request.query_params.get('export') == 'csv'


def _cell(value):
    """Stop spreadsheet apps from running a cell as a formula (CSV injection)."""
    text = '' if value is None else str(value)
    return f"'{text}" if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def csv_response(filename, columns, rows):
    """columns: [(header, key)], rows: dicts. Streams at most EXPORT_LIMIT rows."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('﻿')   # BOM so Excel opens ₹ and Telugu/Hindi names correctly
    writer = csv.writer(response)
    writer.writerow([header for header, _ in columns])
    for row in rows[:EXPORT_LIMIT]:
        writer.writerow([_cell(row.get(key)) for _, key in columns])
    return response


def export_filename(prefix):
    return f'{prefix}-{timezone.localdate().isoformat()}.csv'


# ---------- per-row totals ----------

def correlated_total(qs, function, field, output):
    """SELECT <function>(<field>) over the rows of `qs` (which uses OuterRef), as one value per outer row, 0 when none.

    A plain aggregate function (not .annotate(Count(...)).values()) keeps the subquery free of GROUP BY, and summing
    in a subquery means two different relations on the same row never multiply each other's totals.
    """
    total = qs.order_by().annotate(v=Func(F(field), function=function, output_field=output)).values('v')[:1]
    return Coalesce(Subquery(total, output_field=output), Value(0, output_field=output))


# ---------- titles and proofs ----------

def title_map(model, ids):
    """{id: English title} for trips or events, falling back to the slug."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    out = {o.pk: o.slug.replace('-', ' ').title() for o in model.objects.filter(pk__in=ids).only('slug')}
    fk = f'{model._meta.model_name}_id'
    rows = model.translations.rel.related_model.objects.filter(**{f'{fk}__in': ids}).values(fk, 'language', 'title')
    best = {}
    for r in rows:
        if r['language'] == 'en' or r[fk] not in best:
            best[r[fk]] = r['title']
    out.update(best)
    return out


def proof_url(reg, request):
    if not reg.payment_screenshot:
        return None
    try:
        return request.build_absolute_uri(reg.payment_screenshot.url)
    except (ValueError, OSError):
        return None


# ---------- booking rows ----------

def paid_by(booking_ids):
    """{booking_id: amount received} from successful payment allocations."""
    paid = defaultdict(lambda: ZERO)
    for r in (PaymentAllocation.objects.filter(booking_id__in=booking_ids, payment__status=Payment.Status.SUCCEEDED)
              .values('booking_id').annotate(t=Sum('amount'))):
        paid[r['booking_id']] = r['t'] or ZERO
    return paid


def _trip_bucket(status):
    return 'awaiting' if status in TRIP_AWAITING else 'paid' if status in TRIP_PAID else 'cancelled'


def _event_bucket(status):
    return {'PENDING': 'awaiting', 'CONFIRMED': 'paid'}.get(status, 'cancelled')


def trip_booking_rows(bookings, titles):
    paid = paid_by([b.pk for b in bookings])
    return [{
        'id': str(b.pk), 'type': 'trip', 'reference': b.reference,
        'name': b.primary_booker.full_name or b.primary_booker.phone_number, 'phone': b.primary_booker.phone_number,
        'customer_id': str(b.primary_booker_id),
        'title': titles.get(b.schedule.trip_id, ''), 'parent_id': str(b.schedule.trip_id), 'starts_at': _iso(b.schedule.starts_at),
        'people': b.participant_count, 'total': _money(b.total_amount), 'paid': _money(paid[b.pk]),
        'due': _money(ZERO if b.status in TRIP_CANCELLED else max(ZERO, b.total_amount - paid[b.pk])),
        'status': b.status, 'status_label': b.get_status_display(), 'bucket': _trip_bucket(b.status),
        'advance_due': _money(ZERO if b.status in TRIP_CANCELLED else max(ZERO, b.advance_amount - paid[b.pk])),
        'checkout_id': str(b.checkout_id), 'created_at': _iso(b.created_at),
    } for b in bookings]


def event_booking_rows(regs, titles, request, duplicate_utrs=frozenset()):
    rows = []
    for r in regs:
        st = r.effective_status
        rows.append({
            'id': str(r.pk), 'type': 'event', 'reference': r.reference, 'name': r.contact_name or '—', 'phone': r.contact_phone,
            'customer_id': str(r.registrant_id) if r.registrant_id else None,
            'title': titles.get(r.schedule.event_id, ''), 'parent_id': str(r.schedule.event_id), 'starts_at': _iso(r.schedule.starts_at),
            'people': r.participant_count, 'total': _money(r.total_amount),
            'paid': _money(r.total_amount if st == 'CONFIRMED' else ZERO), 'due': _money(r.total_amount if st == 'PENDING' else ZERO),
            'status': st, 'status_label': EventRegistration.Status(st).label, 'bucket': _event_bucket(st),
            'proof_url': proof_url(r, request), 'utr': r.payment_utr, 'utr_duplicate': r.payment_utr in duplicate_utrs,
            'note': r.customer_note, 'staff_note': r.staff_note, 'created_at': _iso(r.created_at),
        })
    return rows


def event_status_q(bucket, now):
    holding = Q(reserved_until__isnull=True) | Q(reserved_until__gt=now)
    if bucket == 'awaiting':
        return Q(status='PENDING') & holding
    if bucket == 'paid':
        return Q(status='CONFIRMED')
    if bucket == 'cancelled':
        return Q(status__in=['CANCELLED', 'EXPIRED']) | (Q(status='PENDING') & ~holding)
    return Q()
