"""Staff home: the dashboard, friendly list pages (bookings, payments, customers), a customer page, global search and badge counts.

Every endpoint returns rows ready to show (names, titles, money as strings), so the admin never displays raw ids.
Numbers reuse the rules in overview.py: trip money = successful payment allocations; an event booking counts as paid once CONFIRMED.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from bookings.models import Booking
from crm.models import Enquiry
from payments.models import Payment, PaymentAllocation
from trips.models import Event, EventRegistration, EventSchedule, Trip, TripSchedule

from .overview import ZERO, _can, _iso, _money
from .permissions import StaffOnly
from .views import AdminDashboardView, _access_log, _resolve

PAGE = 25
TRIP_AWAITING = [Booking.Status.PENDING_ADVANCE, Booking.Status.CONFIRMED]
TRIP_PAID = [Booking.Status.FULLY_PAID, Booking.Status.COMPLETED]
TRIP_CANCELLED = [Booking.Status.CANCELLED, Booking.Status.NO_SHOW]


# ---------- small helpers ----------

def _titles(model, ids):
    """{id: English title} for trips or events, falling back to the slug."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    out = {o.pk: o.slug.replace('-', ' ').title() for o in model.objects.filter(pk__in=ids).only('slug')}
    rows = model.translations.rel.related_model.objects.filter(**{f'{model._meta.model_name}_id__in': ids}).values(f'{model._meta.model_name}_id', 'language', 'title')
    best = {}
    for r in rows:
        key = r[f'{model._meta.model_name}_id']
        if r['language'] == 'en' or key not in best:
            best[key] = r['title']
    out.update(best)
    return out


def _proof(reg, request):
    if not reg.payment_screenshot:
        return None
    try:
        return request.build_absolute_uri(reg.payment_screenshot.url)
    except (ValueError, OSError):
        return None


def _page(request, qs):
    paginator = Paginator(qs, PAGE)
    try:
        number = max(1, int(request.query_params.get('page', 1)))
    except ValueError:
        number = 1
    try:
        page = paginator.page(number)
    except EmptyPage:
        page = paginator.page(paginator.num_pages or 1)
    return page, {'count': paginator.count, 'page': page.number, 'pages': paginator.num_pages or 1}


def _paid_by(booking_ids):
    paid = defaultdict(lambda: ZERO)
    for r in (PaymentAllocation.objects.filter(booking_id__in=booking_ids, payment__status=Payment.Status.SUCCEEDED)
              .values('booking_id').annotate(t=Sum('amount'))):
        paid[r['booking_id']] = r['t'] or ZERO
    return paid


def _trip_bucket(status):
    return 'awaiting' if status in TRIP_AWAITING else 'paid' if status in TRIP_PAID else 'cancelled'


def _event_bucket(status):
    return {'PENDING': 'awaiting', 'CONFIRMED': 'paid'}.get(status, 'cancelled')


def _trip_booking_rows(bookings, titles):
    paid = _paid_by([b.pk for b in bookings])
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


def _event_booking_rows(regs, titles, request):
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
            'proof_url': _proof(r, request), 'utr': r.payment_utr, 'note': r.customer_note, 'created_at': _iso(r.created_at),
        })
    return rows


def _event_status_q(bucket, now):
    holding = Q(reserved_until__isnull=True) | Q(reserved_until__gt=now)
    if bucket == 'awaiting':
        return Q(status='PENDING') & holding
    if bucket == 'paid':
        return Q(status='CONFIRMED')
    if bucket == 'cancelled':
        return Q(status__in=['CANCELLED', 'EXPIRED']) | (Q(status='PENDING') & ~holding)
    return Q()


# ---------- dashboard ----------

class HomeView(APIView):
    """Everything the dashboard shows, filtered by what the staff member may see."""
    permission_classes = [StaffOnly]

    def get(self, request):
        u = request.user
        now = timezone.now()
        today = timezone.localdate()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        see_trips = _can(request, 'bookings')
        see_pay = _can(request, 'payments')
        see_events = _can(request, 'event-registrations')

        def trip_money(lo, hi):
            return Payment.objects.filter(status=Payment.Status.SUCCEEDED, created_at__gte=lo, created_at__lt=hi).aggregate(t=Sum('amount'))['t'] or ZERO

        def event_money(lo, hi):
            return EventRegistration.objects.filter(status='CONFIRMED', confirmed_at__gte=lo, confirmed_at__lt=hi).aggregate(t=Sum('total_amount'))['t'] or ZERO

        def bookings_between(lo, hi):
            n = 0
            if see_trips:
                n += Booking.objects.filter(created_at__gte=lo, created_at__lt=hi).exclude(status__in=TRIP_CANCELLED).count()
            if see_events:
                n += EventRegistration.objects.filter(created_at__gte=lo, created_at__lt=hi).exclude(status='CANCELLED').count()
            return n

        def delta(cur, prev):
            cur, prev = float(cur), float(prev)
            return round((cur - prev) / prev * 100, 1) if prev else None

        # comparisons use the same number of days into last month, so the 3rd of the month isn't compared with all of last month
        same_point_last_month = prev_month_start + (now - month_start)
        kpis = []
        if see_pay or see_events:
            cur = (trip_money(month_start, now) if see_pay else ZERO) + (event_money(month_start, now) if see_events else ZERO)
            prev = (trip_money(prev_month_start, same_point_last_month) if see_pay else ZERO) + (event_money(prev_month_start, same_point_last_month) if see_events else ZERO)
            kpis.append({'key': 'revenue', 'label': 'Revenue this month', 'value': _money(cur), 'format': 'money', 'delta': delta(cur, prev), 'hint': 'Trip payments received + confirmed event bookings'})
        if see_trips or see_events:
            cur, prev = bookings_between(month_start, now), bookings_between(prev_month_start, same_point_last_month)
            kpis.append({'key': 'bookings', 'label': 'Bookings this month', 'value': cur, 'format': 'number', 'delta': delta(cur, prev), 'hint': 'Trips and events, not counting cancelled'})

        # who is going out in the next 7 days
        week = now + timedelta(days=7)
        upcoming = []
        if _can(request, 'trips'):
            for s in TripSchedule.objects.filter(starts_at__gte=now, starts_at__lt=now + timedelta(days=14)).select_related('trip').order_by('starts_at')[:12]:
                upcoming.append({'kind': 'trip', 'parent_id': str(s.trip_id), 'schedule_id': str(s.pk), 'starts_at': _iso(s.starts_at),
                                 'booked': s.seats_booked, 'capacity': s.capacity, 'is_open': s.is_open})
        if _can(request, 'events'):
            for s in EventSchedule.objects.filter(starts_at__gte=now - timedelta(hours=12), starts_at__lt=now + timedelta(days=14)).select_related('event').order_by('starts_at')[:12]:
                upcoming.append({'kind': 'event', 'parent_id': str(s.event_id), 'schedule_id': str(s.pk), 'starts_at': _iso(s.starts_at),
                                 'booked': s.reserved_count(now), 'capacity': s.capacity, 'is_open': not s.has_started(now)})
        trip_titles = _titles(Trip, [x['parent_id'] for x in upcoming if x['kind'] == 'trip'])
        event_titles = _titles(Event, [x['parent_id'] for x in upcoming if x['kind'] == 'event'])
        import uuid as _uuid
        for x in upcoming:
            x['title'] = (trip_titles if x['kind'] == 'trip' else event_titles).get(_uuid.UUID(x['parent_id']), '')
        upcoming.sort(key=lambda x: x['starts_at'])
        this_week = [x for x in upcoming if x['starts_at'] < week.isoformat()]
        kpis.append({'key': 'departures', 'label': 'Going out in 7 days', 'value': len(this_week), 'format': 'number', 'delta': None,
                     'hint': f'{sum(x["booked"] for x in this_week)} people booked'})

        # ---- to-do: things a person has to act on ----
        todo = {}
        if see_pay:
            qs = Payment.objects.filter(status=Payment.Status.PENDING_VERIFICATION).select_related('payer').prefetch_related('allocations__booking__schedule').order_by('created_at')
            items = list(qs[:5])
            tids = {a.booking.schedule.trip_id for p in items for a in p.allocations.all()}
            titles = _titles(Trip, tids)
            todo['verify_payments'] = {'count': qs.count(), 'items': [{
                'id': str(p.pk), 'amount': _money(p.amount), 'payer': p.payer.full_name or p.payer.phone_number, 'reference': p.manual_reference,
                'kind': p.kind, 'created_at': _iso(p.created_at),
                'title': ', '.join(sorted({titles.get(a.booking.schedule.trip_id, '') for a in p.allocations.all()})),
                'parent_id': next((str(a.booking.schedule.trip_id) for a in p.allocations.all()), None),
            } for p in items]}
        if see_events:
            qs = EventRegistration.objects.filter(_event_status_q('awaiting', now)).select_related('schedule').order_by('-payment_submitted_at', 'created_at')
            items = list(qs[:6])
            titles = _titles(Event, {r.schedule.event_id for r in items})
            todo['confirm_events'] = {'count': qs.count(), 'with_proof': qs.exclude(payment_screenshot='').count(),
                                      'items': _event_booking_rows(items, titles, request)}
        if see_trips:
            soon = Booking.objects.filter(status__in=TRIP_AWAITING, schedule__starts_at__gte=now, schedule__starts_at__lt=now + timedelta(days=14)).select_related('primary_booker', 'schedule').order_by('schedule__starts_at')
            rows = [r for r in _trip_booking_rows(list(soon[:30]), _titles(Trip, {b.schedule.trip_id for b in soon[:30]})) if Decimal(r['due']) > 0]
            todo['balance_due'] = {'count': len(rows), 'items': rows[:5]}
        if _can(request, 'enquiries'):
            qs = Enquiry.objects.filter(status=Enquiry.Status.NEW).order_by('-created_at')
            todo['enquiries'] = {'count': qs.count(), 'items': [{
                'id': str(e.pk), 'name': e.name, 'phone': e.phone, 'message': (e.message or '')[:160], 'created_at': _iso(e.created_at),
            } for e in qs[:5]]}

        # ---- charts ----
        start = today - timedelta(days=29)
        days = defaultdict(lambda: {'trips': ZERO, 'events': ZERO})
        if see_pay:
            for r in (Payment.objects.filter(status=Payment.Status.SUCCEEDED, created_at__date__gte=start)
                      .annotate(d=TruncDate('created_at')).values('d').annotate(t=Sum('amount'))):
                days[r['d']]['trips'] += r['t'] or ZERO
        if see_events:
            for r in (EventRegistration.objects.filter(status='CONFIRMED', confirmed_at__date__gte=start)
                      .annotate(d=TruncDate('confirmed_at')).values('d').annotate(t=Sum('total_amount'))):
                days[r['d']]['events'] += r['t'] or ZERO
        revenue_30d = [{'date': (start + timedelta(days=i)).isoformat(),
                        'trips': float(days[start + timedelta(days=i)]['trips']), 'events': float(days[start + timedelta(days=i)]['events'])}
                       for i in range(30)]

        # top sellers in the last 90 days
        since = now - timedelta(days=90)
        top = []
        if see_pay:
            for r in (PaymentAllocation.objects.filter(payment__status=Payment.Status.SUCCEEDED, created_at__gte=since)
                      .values('booking__schedule__trip_id').annotate(t=Sum('amount'), n=Count('booking', distinct=True)).order_by('-t')[:5]):
                top.append({'kind': 'trip', 'parent_id': r['booking__schedule__trip_id'], 'revenue': r['t'] or ZERO, 'bookings': r['n']})
        if see_events:
            for r in (EventRegistration.objects.filter(status='CONFIRMED', confirmed_at__gte=since)
                      .values('schedule__event_id').annotate(t=Sum('total_amount'), n=Count('id')).order_by('-t')[:5]):
                top.append({'kind': 'event', 'parent_id': r['schedule__event_id'], 'revenue': r['t'] or ZERO, 'bookings': r['n']})
        tt = _titles(Trip, [x['parent_id'] for x in top if x['kind'] == 'trip'])
        et = _titles(Event, [x['parent_id'] for x in top if x['kind'] == 'event'])
        top.sort(key=lambda x: x['revenue'], reverse=True)
        top = [{**x, 'title': (tt if x['kind'] == 'trip' else et).get(x['parent_id'], ''), 'parent_id': str(x['parent_id']), 'revenue': _money(x['revenue'])} for x in top[:6]]

        # ---- what just happened ----
        activity = []
        if see_trips:
            recent = list(Booking.objects.select_related('primary_booker', 'schedule').order_by('-created_at')[:8])
            titles = _titles(Trip, {b.schedule.trip_id for b in recent})
            activity += [{'type': 'trip-booking', 'at': _iso(b.created_at), 'name': b.primary_booker.full_name or b.primary_booker.phone_number,
                          'text': f'booked {titles.get(b.schedule.trip_id, "a trip")}', 'amount': _money(b.total_amount), 'status': b.status,
                          'href': f'/admin/overview/trip/{b.schedule.trip_id}'} for b in recent]
        if see_events:
            recent = list(EventRegistration.objects.select_related('schedule').order_by('-created_at')[:8])
            titles = _titles(Event, {r.schedule.event_id for r in recent})
            activity += [{'type': 'event-booking', 'at': _iso(r.created_at), 'name': r.contact_name or 'Someone',
                          'text': f'booked {titles.get(r.schedule.event_id, "an event")} × {r.participant_count}', 'amount': _money(r.total_amount),
                          'status': r.effective_status, 'href': f'/admin/overview/event/{r.schedule.event_id}'} for r in recent]
        if see_pay:
            activity += [{'type': 'payment', 'at': _iso(p.created_at), 'name': p.payer.full_name or p.payer.phone_number,
                          'text': f'paid ({p.get_method_display().lower()}, {p.kind.lower()})', 'amount': _money(p.amount), 'status': p.status,
                          'href': '/admin/payments/payments'} for p in Payment.objects.select_related('payer').exclude(status=Payment.Status.CREATED).order_by('-created_at')[:8]]
        activity.sort(key=lambda a: a['at'], reverse=True)

        legacy = AdminDashboardView()
        return Response({
            'name': (u.full_name or '').split(' ')[0] or None,
            'kpis': kpis, 'todo': todo, 'revenue_30d': revenue_30d, 'upcoming': upcoming, 'top': top, 'activity': activity[:12],
            'setup': legacy._setup(u), 'as_of': _iso(now),
            'can': {'trips': _can(request, 'trips'), 'events': _can(request, 'events'), 'add_trip': _can(request, 'trips', 'add'),
                    'add_event': _can(request, 'events', 'add'), 'verify_payment': _can(request, 'payments', 'change'),
                    'confirm_event': _can(request, 'event-registrations', 'change')},
        })


class CountsView(APIView):
    """Badge numbers for the sidebar: work waiting for someone."""
    permission_classes = [StaffOnly]

    def get(self, request):
        now = timezone.now()
        out = {}
        if _can(request, 'payments'):
            out['payments'] = Payment.objects.filter(status=Payment.Status.PENDING_VERIFICATION).count()
        if _can(request, 'event-registrations'):
            out['event_bookings'] = EventRegistration.objects.filter(_event_status_q('awaiting', now)).count()
        if _can(request, 'enquiries'):
            out['enquiries'] = Enquiry.objects.filter(status=Enquiry.Status.NEW).count()
        return Response(out)


# ---------- list pages ----------

class BookingListView(APIView):
    """Trip or event bookings as friendly rows, with counts for the status filter."""
    permission_classes = [StaffOnly]

    def get(self, request):
        kind = request.query_params.get('type', 'trip')
        bucket = request.query_params.get('status', 'all')
        q = request.query_params.get('search', '').strip()
        now = timezone.now()
        if kind == 'event':
            from .views import _require_model_permission
            _require_model_permission(request, _resolve('event-registrations'), 'view')
            base = EventRegistration.objects.select_related('schedule')
            if q:
                base = base.filter(Q(reference__icontains=q) | Q(contact_name__icontains=q) | Q(contact_phone__icontains=q) | Q(schedule__event__slug__icontains=q)
                                   | Q(schedule__event__translations__title__icontains=q)).distinct()
            counts = {b: base.filter(_event_status_q(b, now)).count() for b in ('awaiting', 'paid', 'cancelled')}
            qs = base.filter(_event_status_q(bucket, now)).order_by('-created_at')
            page, meta = _page(request, qs)
            regs = list(page.object_list)
            rows = _event_booking_rows(regs, _titles(Event, {r.schedule.event_id for r in regs}), request)
            _access_log(request, _resolve('event-registrations'), purpose='bookings list')
        else:
            from .views import _require_model_permission
            _require_model_permission(request, _resolve('bookings'), 'view')
            base = Booking.objects.select_related('primary_booker', 'schedule')
            if q:
                base = base.filter(Q(reference__icontains=q) | Q(primary_booker__full_name__icontains=q) | Q(primary_booker__phone_number__icontains=q)
                                   | Q(schedule__trip__slug__icontains=q) | Q(schedule__trip__translations__title__icontains=q)).distinct()
            groups = {'awaiting': TRIP_AWAITING, 'paid': TRIP_PAID, 'cancelled': TRIP_CANCELLED}
            counts = {b: base.filter(status__in=s).count() for b, s in groups.items()}
            qs = (base.filter(status__in=groups[bucket]) if bucket in groups else base).order_by('-created_at')
            page, meta = _page(request, qs)
            items = list(page.object_list)
            rows = _trip_booking_rows(items, _titles(Trip, {b.schedule.trip_id for b in items}))
            _access_log(request, _resolve('bookings'), purpose='bookings list')
        counts['all'] = sum(counts.values())
        return Response({**meta, 'counts': counts, 'results': rows,
                         'can': {'cancel': request.user.has_perm('bookings.change_booking') if kind != 'event' else _can(request, 'event-registrations', 'change'),
                                 'confirm': _can(request, 'event-registrations', 'change'), 'record_payment': request.user.has_perm('payments.add_payment')}})


class PaymentListView(APIView):
    """Trip payments (gateway + manual). Event payments are the UPI proofs on event bookings, listed with type=event."""
    permission_classes = [StaffOnly]

    def get(self, request):
        from .views import _require_model_permission
        kind = request.query_params.get('type', 'trip')
        bucket = request.query_params.get('status', 'all')
        q = request.query_params.get('search', '').strip()
        if kind == 'event':
            _require_model_permission(request, _resolve('event-registrations'), 'view')
            base = EventRegistration.objects.select_related('schedule').exclude(payment_screenshot='', payment_utr='')
            if q:
                base = base.filter(Q(reference__icontains=q) | Q(contact_name__icontains=q) | Q(contact_phone__icontains=q) | Q(payment_utr__icontains=q))
            now = timezone.now()
            groups = {'pending': _event_status_q('awaiting', now), 'succeeded': Q(status='CONFIRMED'), 'failed': _event_status_q('cancelled', now)}
            counts = {k: base.filter(v).count() for k, v in groups.items()}
            qs = (base.filter(groups[bucket]) if bucket in groups else base).order_by('-payment_submitted_at', '-created_at')
            page, meta = _page(request, qs)
            regs = list(page.object_list)
            rows = _event_booking_rows(regs, _titles(Event, {r.schedule.event_id for r in regs}), request)
        else:
            _require_model_permission(request, _resolve('payments'), 'view')
            base = Payment.objects.exclude(status=Payment.Status.CREATED).select_related('payer').prefetch_related('allocations__booking__schedule')
            if q:
                base = base.filter(Q(manual_reference__icontains=q) | Q(payer__full_name__icontains=q) | Q(payer__phone_number__icontains=q)
                                   | Q(allocations__booking__reference__icontains=q)).distinct()
            groups = {'pending': [Payment.Status.PENDING_VERIFICATION], 'succeeded': [Payment.Status.SUCCEEDED],
                      'failed': [Payment.Status.FAILED, Payment.Status.REJECTED]}
            counts = {k: base.filter(status__in=v).count() for k, v in groups.items()}
            qs = (base.filter(status__in=groups[bucket]) if bucket in groups else base).order_by('-created_at')
            page, meta = _page(request, qs)
            items = list(page.object_list)
            titles = _titles(Trip, {a.booking.schedule.trip_id for p in items for a in p.allocations.all()})
            rows = [{
                'id': str(p.pk), 'amount': _money(p.amount), 'status': p.status, 'kind': p.kind, 'method': p.method, 'reference': p.manual_reference,
                'name': p.payer.full_name or p.payer.phone_number, 'phone': p.payer.phone_number, 'customer_id': str(p.payer_id),
                'bookings': sorted({a.booking.reference for a in p.allocations.all()}),
                'title': ', '.join(sorted({titles.get(a.booking.schedule.trip_id, '') for a in p.allocations.all()} - {''})),
                'parent_id': next((str(a.booking.schedule.trip_id) for a in p.allocations.all()), None),
                'failure_reason': p.failure_reason, 'created_at': _iso(p.created_at),
            } for p in items]
        counts['all'] = sum(counts.values())
        _access_log(request, _resolve('payments' if kind != 'event' else 'event-registrations'), purpose='payments list')
        return Response({**meta, 'counts': counts, 'results': rows,
                         'can': {'verify': _can(request, 'payments', 'change'), 'confirm': _can(request, 'event-registrations', 'change')}})


def _customers(request):
    from .views import _queryset
    return _queryset(_resolve('customers'), request.user, request.tenant).distinct()


class CustomerListView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        from .views import _require_model_permission
        _require_model_permission(request, _resolve('customers'), 'view')
        q = request.query_params.get('search', '').strip()
        qs = _customers(request)
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(phone_number__icontains=q) | Q(email__icontains=q))
        page, meta = _page(request, qs.order_by('-date_joined'))
        users = list(page.object_list)
        ids = [x.pk for x in users]
        phones = [x.phone_number for x in users]
        trips = {r['primary_booker_id']: r for r in Booking.objects.filter(primary_booker_id__in=ids).exclude(status__in=TRIP_CANCELLED)
                 .values('primary_booker_id').annotate(n=Count('id'))}
        spent = {r['payer_id']: r['t'] for r in Payment.objects.filter(payer_id__in=ids, status=Payment.Status.SUCCEEDED).values('payer_id').annotate(t=Sum('amount'))}
        events = defaultdict(lambda: {'n': 0, 't': ZERO})
        for r in EventRegistration.objects.filter(Q(registrant_id__in=ids) | Q(contact_phone__in=phones)).exclude(status__in=['CANCELLED', 'EXPIRED']):
            owner = r.registrant_id if r.registrant_id in ids else next((x.pk for x in users if x.phone_number == r.contact_phone), None)
            if owner:
                events[owner]['n'] += 1
                if r.status == 'CONFIRMED':
                    events[owner]['t'] += r.total_amount
        rows = [{
            'id': str(x.pk), 'name': x.full_name or '—', 'phone': x.phone_number, 'email': x.email, 'joined': _iso(x.date_joined),
            'trip_bookings': trips.get(x.pk, {}).get('n', 0), 'event_bookings': events[x.pk]['n'],
            'spent': _money((spent.get(x.pk) or ZERO) + events[x.pk]['t']), 'active': x.is_active,
        } for x in users]
        _access_log(request, _resolve('customers'), purpose='customers list')
        return Response({**meta, 'results': rows})


class CustomerDetailView(APIView):
    """One customer with every booking, payment and enquiry."""
    permission_classes = [StaffOnly]

    def get(self, request, pk):
        from .views import _require_model_permission
        _require_model_permission(request, _resolve('customers'), 'view')
        try:
            c = _customers(request).get(pk=pk)
        except Exception:   # noqa: BLE001 - not found / bad id
            raise Http404('Customer not found.')
        trip_rows, event_rows, pay_rows, enquiries = [], [], [], []
        if _can(request, 'bookings'):
            bs = list(Booking.objects.filter(primary_booker=c).select_related('primary_booker', 'schedule').order_by('-created_at'))
            trip_rows = _trip_booking_rows(bs, _titles(Trip, {b.schedule.trip_id for b in bs}))
        if _can(request, 'event-registrations'):
            rs = list(EventRegistration.objects.filter(Q(registrant=c) | Q(contact_phone=c.phone_number)).select_related('schedule').order_by('-created_at'))
            event_rows = _event_booking_rows(rs, _titles(Event, {r.schedule.event_id for r in rs}), request)
        if _can(request, 'payments'):
            pay_rows = [{'id': str(p.pk), 'amount': _money(p.amount), 'status': p.status, 'kind': p.kind, 'method': p.method,
                         'reference': p.manual_reference, 'created_at': _iso(p.created_at)}
                        for p in Payment.objects.filter(payer=c).exclude(status=Payment.Status.CREATED).order_by('-created_at')]
        if _can(request, 'enquiries'):
            enquiries = [{'id': str(e.pk), 'message': e.message, 'status': e.status, 'created_at': _iso(e.created_at)}
                         for e in Enquiry.objects.filter(phone=c.phone_number).order_by('-created_at')[:20]]
        spent = sum((Decimal(r['paid']) for r in trip_rows + event_rows), ZERO)
        due = sum((Decimal(r['due']) for r in trip_rows + event_rows), ZERO)
        _access_log(request, _resolve('customers'), c, purpose='customer page')
        return Response({
            'id': str(c.pk), 'name': c.full_name or c.phone_number, 'phone': c.phone_number, 'email': c.email,
            'language': c.preferred_language, 'joined': _iso(c.date_joined), 'active': c.is_active,
            'stats': {'trip_bookings': len([r for r in trip_rows if r['bucket'] != 'cancelled']),
                      'event_bookings': len([r for r in event_rows if r['bucket'] != 'cancelled']),
                      'spent': _money(spent), 'due': _money(due)},
            'trip_bookings': trip_rows, 'event_bookings': event_rows, 'payments': pay_rows, 'enquiries': enquiries,
            'can_edit': _can(request, 'customers', 'change'),
        })


# ---------- search ----------

class SearchView(APIView):
    """⌘K: find trips, events, bookings and customers by name, phone or reference."""
    permission_classes = [StaffOnly]

    def get(self, request):
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response({'results': []})
        out = []
        if _can(request, 'trips'):
            trips = list(Trip.objects.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()[:5])
            titles = _titles(Trip, [t.pk for t in trips])
            out += [{'type': 'Trip', 'label': titles.get(t.pk, t.slug), 'sub': t.get_status_display(), 'href': f'/admin/overview/trip/{t.pk}'} for t in trips]
        if _can(request, 'events'):
            events = list(Event.objects.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()[:5])
            titles = _titles(Event, [e.pk for e in events])
            out += [{'type': 'Event', 'label': titles.get(e.pk, e.slug), 'sub': e.get_status_display(), 'href': f'/admin/overview/event/{e.pk}'} for e in events]
        if _can(request, 'bookings'):
            for b in Booking.objects.filter(Q(reference__icontains=q) | Q(primary_booker__phone_number__icontains=q) | Q(primary_booker__full_name__icontains=q)).select_related('primary_booker', 'schedule')[:5]:
                out.append({'type': 'Trip booking', 'label': f'{b.reference} · {b.primary_booker.full_name or b.primary_booker.phone_number}',
                            'sub': b.get_status_display(), 'href': f'/admin/overview/trip/{b.schedule.trip_id}?tab=bookings'})
        if _can(request, 'event-registrations'):
            for r in EventRegistration.objects.filter(Q(reference__icontains=q) | Q(contact_phone__icontains=q) | Q(contact_name__icontains=q)).select_related('schedule')[:5]:
                out.append({'type': 'Event booking', 'label': f'{r.reference} · {r.contact_name}', 'sub': EventRegistration.Status(r.effective_status).label,
                            'href': f'/admin/overview/event/{r.schedule.event_id}?tab=bookings'})
        if _can(request, 'customers'):
            for c in _customers(request).filter(Q(full_name__icontains=q) | Q(phone_number__icontains=q) | Q(email__icontains=q))[:5]:
                out.append({'type': 'Customer', 'label': c.full_name or c.phone_number, 'sub': c.phone_number, 'href': f'/admin/customers/{c.pk}'})
        return Response({'results': out})
