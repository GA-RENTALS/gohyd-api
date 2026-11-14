"""Payments page: trip payments, event UPI proofs, trip refunds and event refunds (sent back by UPI), with a money summary, date filter and CSV export.

GET /admin/lists/payments/?type=trip|event|refund|event_refund&status=…&search=…&from=YYYY-MM-DD&to=YYYY-MM-DD&page=N[&export=csv]
"""
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from payments.models import EventRefund, Payment, PaymentAllocation, Refund
from trips.models import Event, EventRegistration, Trip

from .listing import (TRIP_AWAITING, csv_response, date_range, event_booking_rows, event_status_q, export_filename, in_range,
                      paginate, title_map, wants_export)
from .overview import ZERO, _can, _iso, _money
from .permissions import StaffOnly, staff_has_perm
from .views import _access_log, _require_model_permission, _resolve

TYPES = ('trip', 'event', 'refund', 'event_refund')

TRIP_GROUPS = {
    'pending': [Payment.Status.PENDING_VERIFICATION],
    'succeeded': [Payment.Status.SUCCEEDED],
    'failed': [Payment.Status.FAILED, Payment.Status.REJECTED],
}
REFUND_GROUPS = {
    'pending': [Refund.Status.REQUESTED],
    'processing': [Refund.Status.APPROVED, Refund.Status.PROCESSING],
    'processed': [Refund.Status.PROCESSED],
    'failed': [Refund.Status.FAILED, Refund.Status.REJECTED],
}

TRIP_CSV = [('Date', 'created_at'), ('Paid by', 'name'), ('Phone', 'phone'), ('Amount', 'amount'), ('Status', 'status'),
            ('Type', 'kind'), ('Method', 'method'), ('Reference', 'reference'), ('Trip', 'title'), ('Bookings', 'bookings_text')]
EVENT_CSV = [('Booked', 'created_at'), ('Name', 'name'), ('Phone', 'phone'), ('Event', 'title'), ('Reference', 'reference'),
             ('People', 'people'), ('Amount', 'total'), ('Status', 'status_label'), ('UPI reference', 'utr')]
EVENT_REFUND_GROUPS = {
    'due': [EventRefund.Status.DUE],
    'sent': [EventRefund.Status.SENT],
    'not_refunded': [EventRefund.Status.NOT_REFUNDED],
}

REFUND_CSV = [('Requested', 'created_at'), ('Customer', 'name'), ('Phone', 'phone'), ('Amount', 'amount'), ('Status', 'status'),
              ('Booking', 'booking'), ('Trip', 'title'), ('Reason', 'reason'), ('Approved by', 'approved_by')]
EVENT_REFUND_CSV = [('Cancelled', 'created_at'), ('Customer', 'name'), ('Phone', 'phone'), ('Event', 'title'), ('Booking', 'reference'),
                    ('Paid', 'paid'), ('Refund', 'amount'), ('Status', 'status_label'), ('UPI reference', 'upi_reference'),
                    ('Cancelled by', 'cancelled_by'), ('Reason', 'reason'), ('Note', 'note'), ('Recorded by', 'recorded_by')]


class PaymentListView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        kind = request.query_params.get('type', 'trip')
        if kind not in TYPES:
            raise ValidationError({'type': f'Use one of: {", ".join(TYPES)}.'})
        bucket = request.query_params.get('status', 'all')
        search = request.query_params.get('search', '').strip()
        start, end = date_range(request)
        build = {'trip': self._trip, 'event': self._event, 'refund': self._refund, 'event_refund': self._event_refund}[kind]
        qs, groups, to_rows, columns = build(request, search, start, end)

        counts = {key: qs.filter(q).count() for key, q in groups.items()}
        counts['all'] = sum(counts.values())
        qs = qs.filter(groups[bucket]) if bucket in groups else qs

        if wants_export(request):
            _access_log(request, self._resource(kind), purpose=f'{kind} payments export')
            name = {'refund': 'refunds', 'event_refund': 'event-refunds'}.get(kind, f'{kind}-payments')
            return csv_response(export_filename(name), columns, to_rows(list(qs)))

        page, meta = paginate(request, qs)
        _access_log(request, self._resource(kind), purpose='payments list')
        return Response({**meta, 'counts': counts, 'results': to_rows(list(page.object_list)),
                         'summary': payment_summary(request), 'can': self._can(request)})

    # ---- one builder per tab: (queryset, {bucket: Q}, rows(list) -> dicts, CSV columns) ----

    @staticmethod
    def _trip(request, search, start, end):
        _require_model_permission(request, _resolve('payments'), 'view')
        qs = (Payment.objects.exclude(status=Payment.Status.CREATED).select_related('payer')
              .prefetch_related('allocations__booking__schedule').order_by('-created_at'))
        if search:
            qs = qs.filter(Q(manual_reference__icontains=search) | Q(payer__full_name__icontains=search)
                           | Q(payer__phone_number__icontains=search) | Q(allocations__booking__reference__icontains=search)).distinct()
        qs = in_range(qs, 'created_at', start, end)
        groups = {key: Q(status__in=statuses) for key, statuses in TRIP_GROUPS.items()}
        return qs, groups, trip_payment_rows, TRIP_CSV

    @staticmethod
    def _event(request, search, start, end):
        _require_model_permission(request, _resolve('event-registrations'), 'view')
        qs = (EventRegistration.objects.select_related('schedule').exclude(payment_screenshot='', payment_utr='')
              .annotate(paid_on=Coalesce('payment_submitted_at', 'created_at')).order_by('-paid_on'))
        if search:
            qs = qs.filter(Q(reference__icontains=search) | Q(contact_name__icontains=search)
                           | Q(contact_phone__icontains=search) | Q(payment_utr__icontains=search))
        qs = in_range(qs, 'paid_on', start, end)
        now = timezone.now()
        groups = {'pending': event_status_q('awaiting', now), 'succeeded': Q(status='CONFIRMED'), 'failed': event_status_q('cancelled', now)}

        def rows(regs):
            titles = title_map(Event, {r.schedule.event_id for r in regs})
            return event_booking_rows(regs, titles, request, duplicate_utrs=duplicate_utrs(regs))
        return qs, groups, rows, EVENT_CSV

    @staticmethod
    def _refund(request, search, start, end):
        _require_model_permission(request, _resolve('refunds'), 'view')
        qs = Refund.objects.select_related('booking__primary_booker', 'booking__schedule', 'approved_by').order_by('-created_at')
        if search:
            qs = qs.filter(Q(booking__reference__icontains=search) | Q(booking__primary_booker__full_name__icontains=search)
                           | Q(booking__primary_booker__phone_number__icontains=search) | Q(reason__icontains=search))
        qs = in_range(qs, 'created_at', start, end)
        groups = {key: Q(status__in=statuses) for key, statuses in REFUND_GROUPS.items()}
        return qs, groups, refund_rows, REFUND_CSV

    @staticmethod
    def _event_refund(request, search, start, end):
        _require_model_permission(request, _resolve('event-refunds'), 'view')
        qs = EventRefund.objects.select_related('registration__schedule', 'recorded_by').order_by('-created_at')
        if search:
            qs = qs.filter(Q(registration__reference__icontains=search) | Q(registration__contact_name__icontains=search)
                           | Q(registration__contact_phone__icontains=search) | Q(upi_reference__icontains=search))
        qs = in_range(qs, 'created_at', start, end)
        groups = {key: Q(status__in=statuses) for key, statuses in EVENT_REFUND_GROUPS.items()}
        return qs, groups, event_refund_rows, EVENT_REFUND_CSV

    @staticmethod
    def _resource(kind):
        return _resolve({'trip': 'payments', 'event': 'event-registrations', 'refund': 'refunds', 'event_refund': 'event-refunds'}[kind])

    @staticmethod
    def _can(request):
        return {
            'verify': staff_has_perm(request, 'payments.change_payment'),
            'confirm': _can(request, 'event-registrations', 'change'),
            'approve_refund': staff_has_perm(request, 'payments.change_refund'),
            'refunds': _can(request, 'refunds'),
            'events': _can(request, 'event-registrations'),
            'event_refunds': _can(request, 'event-refunds'),
            'record_event_refund': staff_has_perm(request, 'payments.change_eventrefund'),
        }


# ---------- rows ----------

def trip_payment_rows(payments):
    titles = title_map(Trip, {a.booking.schedule.trip_id for p in payments for a in p.allocations.all()})
    rows = []
    for p in payments:
        allocations = list(p.allocations.all())
        bookings = sorted({a.booking.reference for a in allocations})
        rows.append({
            'id': str(p.pk), 'amount': _money(p.amount), 'status': p.status, 'kind': p.kind, 'method': p.method,
            'reference': p.manual_reference, 'name': p.payer.full_name or p.payer.phone_number, 'phone': p.payer.phone_number,
            'customer_id': str(p.payer_id), 'bookings': bookings, 'bookings_text': ', '.join(bookings),
            'title': ', '.join(sorted({titles.get(a.booking.schedule.trip_id, '') for a in allocations} - {''})),
            'parent_id': next((str(a.booking.schedule.trip_id) for a in allocations), None),
            'failure_reason': p.failure_reason, 'created_at': _iso(p.created_at),
        })
    return rows


def refund_rows(refunds):
    titles = title_map(Trip, {r.booking.schedule.trip_id for r in refunds})
    return [{
        'id': str(r.pk), 'amount': _money(r.amount), 'status': r.status, 'reason': r.reason,
        'booking': r.booking.reference, 'booking_id': str(r.booking_id),
        'name': r.booking.primary_booker.full_name or r.booking.primary_booker.phone_number,
        'phone': r.booking.primary_booker.phone_number, 'customer_id': str(r.booking.primary_booker_id),
        'title': titles.get(r.booking.schedule.trip_id, ''), 'parent_id': str(r.booking.schedule.trip_id),
        'approved_by': (r.approved_by.full_name or r.approved_by.phone_number) if r.approved_by else '',
        'created_at': _iso(r.created_at), 'updated_at': _iso(r.updated_at),
    } for r in refunds]


def event_refund_rows(refunds):
    titles = title_map(Event, {r.registration.schedule.event_id for r in refunds})
    rows = []
    for r in refunds:
        reg = r.registration
        rows.append({
            'id': str(r.pk), 'amount': _money(r.amount), 'status': r.status, 'status_label': r.get_status_display(),
            'percent': r.refund_basis_points / 100, 'paid': _money(reg.total_amount),
            'reference': reg.reference, 'booking_id': str(reg.pk), 'name': reg.contact_name or '—', 'phone': reg.contact_phone,
            'customer_id': str(reg.registrant_id) if reg.registrant_id else None,
            'title': titles.get(reg.schedule.event_id, ''), 'parent_id': str(reg.schedule.event_id), 'starts_at': _iso(reg.schedule.starts_at),
            'cancelled_by': 'Customer' if reg.cancelled_by_customer else 'Staff', 'reason': reg.cancel_reason or reg.staff_note,
            'upi_reference': r.upi_reference, 'note': r.note,
            'recorded_by': (r.recorded_by.full_name or r.recorded_by.phone_number) if r.recorded_by else '',
            'recorded_at': _iso(r.recorded_at), 'created_at': _iso(r.created_at),
        })
    return rows


def duplicate_utrs(regs):
    """UPI references on these bookings that were also typed on another booking (one screenshot reused twice)."""
    utrs = {r.payment_utr.strip() for r in regs if r.payment_utr.strip()}
    if not utrs:
        return frozenset()
    return frozenset(EventRegistration.objects.filter(payment_utr__in=utrs).values('payment_utr')
                     .annotate(n=Count('id')).filter(n__gt=1).values_list('payment_utr', flat=True))


# ---------- summary ----------

def payment_summary(request):
    """The money position at a glance. Each figure is only included when the staff member may see its source."""
    now = timezone.now()
    month_start = timezone.localtime(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    see_trip, see_event, see_refund = _can(request, 'payments'), _can(request, 'event-registrations'), _can(request, 'refunds')
    see_event_refund = _can(request, 'event-refunds')
    out = {}

    if see_trip or see_event:
        trip = (Payment.objects.filter(status=Payment.Status.SUCCEEDED, created_at__gte=month_start)
                .aggregate(t=Sum('amount'))['t'] or ZERO) if see_trip else ZERO
        event = (EventRegistration.objects.filter(status='CONFIRMED', confirmed_at__gte=month_start)
                 .aggregate(t=Sum('total_amount'))['t'] or ZERO) if see_event else ZERO
        out['received_month'] = {'amount': _money(trip + event)}

    to_verify = {'count': 0, 'amount': ZERO}
    if see_trip:
        agg = Payment.objects.filter(status=Payment.Status.PENDING_VERIFICATION).aggregate(n=Count('id'), t=Sum('amount'))
        to_verify['count'] += agg['n']
        to_verify['amount'] += agg['t'] or ZERO
    if see_event:
        agg = (EventRegistration.objects.filter(event_status_q('awaiting', now)).exclude(payment_screenshot='', payment_utr='')
               .aggregate(n=Count('id'), t=Sum('total_amount')))
        to_verify['count'] += agg['n']
        to_verify['amount'] += agg['t'] or ZERO
    if see_trip or see_event:
        out['to_verify'] = {'count': to_verify['count'], 'amount': _money(to_verify['amount'])}

    if see_refund:
        agg = Refund.objects.filter(status=Refund.Status.REQUESTED).aggregate(n=Count('id'), t=Sum('amount'))
        out['refunds_waiting'] = {'count': agg['n'], 'amount': _money(agg['t'] or ZERO)}

    if see_event_refund:
        agg = EventRefund.objects.filter(status=EventRefund.Status.DUE).aggregate(n=Count('id'), t=Sum('amount'))
        out['event_refunds_due'] = {'count': agg['n'], 'amount': _money(agg['t'] or ZERO)}

    if see_trip:
        awaiting = Booking.objects.filter(status__in=TRIP_AWAITING)
        billed = awaiting.aggregate(t=Sum('total_amount'))['t'] or ZERO
        received = (PaymentAllocation.objects.filter(booking__in=awaiting, payment__status=Payment.Status.SUCCEEDED)
                    .aggregate(t=Sum('amount'))['t'] or ZERO)
        out['balance_due'] = {'amount': _money(max(ZERO, billed - received)), 'count': awaiting.count()}

    out['as_of'] = _iso(now)
    return out
