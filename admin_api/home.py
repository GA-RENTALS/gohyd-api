"""Staff home: the dashboard, the bookings list page, global search and badge counts.

Every endpoint returns rows ready to show (names, titles, money as strings), so the admin never displays raw ids.
Numbers reuse the rules in overview.py: trip money = successful payment allocations; an event booking counts as paid once CONFIRMED.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from crm.models import Enquiry
from payments.models import Payment, PaymentAllocation
from trips.models import Event, EventRegistration, EventSchedule, Trip, TripSchedule

from .customers import customer_queryset
from .listing import (TRIP_AWAITING, TRIP_CANCELLED, TRIP_PAID, event_booking_rows, event_status_q, paginate, title_map,
                      trip_booking_rows)
from .overview import ZERO, _can, _iso, _money
from .permissions import StaffOnly, staff_has_perm
from .views import AdminDashboardView, _access_log, _resolve

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
        trip_titles = title_map(Trip, [x['parent_id'] for x in upcoming if x['kind'] == 'trip'])
        event_titles = title_map(Event, [x['parent_id'] for x in upcoming if x['kind'] == 'event'])
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
            titles = title_map(Trip, tids)
            todo['verify_payments'] = {'count': qs.count(), 'items': [{
                'id': str(p.pk), 'amount': _money(p.amount), 'payer': p.payer.full_name or p.payer.phone_number, 'reference': p.manual_reference,
                'kind': p.kind, 'created_at': _iso(p.created_at),
                'title': ', '.join(sorted({titles.get(a.booking.schedule.trip_id, '') for a in p.allocations.all()})),
                'parent_id': next((str(a.booking.schedule.trip_id) for a in p.allocations.all()), None),
            } for p in items]}
        if see_events:
            qs = EventRegistration.objects.filter(event_status_q('awaiting', now)).select_related('schedule').order_by('-payment_submitted_at', 'created_at')
            items = list(qs[:6])
            titles = title_map(Event, {r.schedule.event_id for r in items})
            todo['confirm_events'] = {'count': qs.count(), 'with_proof': qs.exclude(payment_screenshot='').count(),
                                      'items': event_booking_rows(items, titles, request)}
        if see_trips:
            soon = Booking.objects.filter(status__in=TRIP_AWAITING, schedule__starts_at__gte=now, schedule__starts_at__lt=now + timedelta(days=14)).select_related('primary_booker', 'schedule').order_by('schedule__starts_at')
            rows = [r for r in trip_booking_rows(list(soon[:30]), title_map(Trip, {b.schedule.trip_id for b in soon[:30]})) if Decimal(r['due']) > 0]
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
        tt = title_map(Trip, [x['parent_id'] for x in top if x['kind'] == 'trip'])
        et = title_map(Event, [x['parent_id'] for x in top if x['kind'] == 'event'])
        top.sort(key=lambda x: x['revenue'], reverse=True)
        top = [{**x, 'title': (tt if x['kind'] == 'trip' else et).get(x['parent_id'], ''), 'parent_id': str(x['parent_id']), 'revenue': _money(x['revenue'])} for x in top[:6]]

        # ---- what just happened ----
        activity = []
        if see_trips:
            recent = list(Booking.objects.select_related('primary_booker', 'schedule').order_by('-created_at')[:8])
            titles = title_map(Trip, {b.schedule.trip_id for b in recent})
            activity += [{'type': 'trip-booking', 'at': _iso(b.created_at), 'name': b.primary_booker.full_name or b.primary_booker.phone_number,
                          'text': f'booked {titles.get(b.schedule.trip_id, "a trip")}', 'amount': _money(b.total_amount), 'status': b.status,
                          'href': f'/admin/overview/trip/{b.schedule.trip_id}'} for b in recent]
        if see_events:
            recent = list(EventRegistration.objects.select_related('schedule').order_by('-created_at')[:8])
            titles = title_map(Event, {r.schedule.event_id for r in recent})
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
                    'add_event': _can(request, 'events', 'add'), 'verify_payment': staff_has_perm(request, 'payments.change_payment'),
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
            out['event_bookings'] = EventRegistration.objects.filter(event_status_q('awaiting', now)).count()
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
            counts = {b: base.filter(event_status_q(b, now)).count() for b in ('awaiting', 'paid', 'cancelled')}
            qs = base.filter(event_status_q(bucket, now)).order_by('-created_at')
            page, meta = paginate(request, qs)
            regs = list(page.object_list)
            rows = event_booking_rows(regs, title_map(Event, {r.schedule.event_id for r in regs}), request)
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
            page, meta = paginate(request, qs)
            items = list(page.object_list)
            rows = trip_booking_rows(items, title_map(Trip, {b.schedule.trip_id for b in items}))
            _access_log(request, _resolve('bookings'), purpose='bookings list')
        counts['all'] = sum(counts.values())
        return Response({**meta, 'counts': counts, 'results': rows,
                         'can': {'cancel': request.user.has_perm('bookings.change_booking') if kind != 'event' else _can(request, 'event-registrations', 'change'),
                                 'confirm': _can(request, 'event-registrations', 'change'), 'record_payment': request.user.has_perm('payments.add_payment')}})


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
            titles = title_map(Trip, [t.pk for t in trips])
            out += [{'type': 'Trip', 'label': titles.get(t.pk, t.slug), 'sub': t.get_status_display(), 'href': f'/admin/overview/trip/{t.pk}'} for t in trips]
        if _can(request, 'events'):
            events = list(Event.objects.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()[:5])
            titles = title_map(Event, [e.pk for e in events])
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
            for c in customer_queryset(request).filter(Q(full_name__icontains=q) | Q(phone_number__icontains=q) | Q(email__icontains=q))[:5]:
                out.append({'type': 'Customer', 'label': c.full_name or c.phone_number, 'sub': c.phone_number, 'href': f'/admin/customer/{c.pk}'})
        return Response({'results': out})
