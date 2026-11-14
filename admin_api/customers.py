"""Customers: the list (filters, sort, summary, export), one customer's page, blocking and staff notes.

GET  /admin/lists/customers/?status=all|upcoming|due|repeat|blocked&sort=…&search=…&from=…&to=…[&export=csv]
GET  /admin/customers/<id>/
POST /admin/customers/<id>/block/   {blocked: bool, reason}
POST /admin/customers/<id>/notes/   {text, channel}

A customer's event bookings are matched by account *or* by phone number, because people can book an event without
signing in. Totals use subqueries per customer, so a customer with many bookings and payments is never double counted.
"""
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import DecimalField, Exists, F, IntegerField, OuterRef, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from crm.models import CustomerInteraction, Enquiry
from payments.models import Payment
from trips.models import Event, EventRegistration, Trip

from .listing import (TRIP_AWAITING, TRIP_CANCELLED, correlated_total, csv_response, date_range, event_booking_rows,
                      export_filename, in_range, paginate, paid_by, title_map, trip_booking_rows, wants_export)
from .overview import ZERO, _can, _iso, _money
from .permissions import StaffOnly, require_staff_perm, staff_has_perm
from .views import _access_log, _audit, _queryset, _require_model_permission, _resolve

MONEY = DecimalField(max_digits=12, decimal_places=2)
SORTS = {'joined': '-date_joined', 'name': 'full_name', 'spent': '-spent', 'bookings': '-booking_count'}
NOTE_CHANNELS = {'note', 'call', 'whatsapp', 'email', 'in_person'}

CSV_COLUMNS = [('Name', 'name'), ('Phone', 'phone'), ('Email', 'email'), ('Joined', 'joined'), ('Trip bookings', 'trip_bookings'),
               ('Event bookings', 'event_bookings'), ('Spent', 'spent'), ('Due', 'due'), ('Active', 'active')]


def customer_queryset(request):
    """Customers of this operator (the same rows the generic `customers` resource shows)."""
    return _queryset(_resolve('customers'), request.user, request.tenant).distinct()


def _events_of_customer():
    """Event bookings that belong to the customer in the outer query: made while signed in, or with their phone."""
    return EventRegistration.objects.filter(Q(registrant=OuterRef('pk')) | Q(contact_phone=OuterRef('phone_number')))


def with_totals(qs):
    """Adds trip_bookings, event_bookings, booking_count, spent and the flags behind the Upcoming / Balance due filters."""
    now = timezone.now()
    trips = Booking.objects.filter(primary_booker=OuterRef('pk')).exclude(status__in=TRIP_CANCELLED)
    events = _events_of_customer().exclude(status__in=['CANCELLED', 'EXPIRED'])
    holding = Q(reserved_until__isnull=True) | Q(reserved_until__gt=now)
    qs = qs.annotate(
        trip_bookings=correlated_total(trips, 'COUNT', 'id', IntegerField()),
        event_bookings=correlated_total(events, 'COUNT', 'id', IntegerField()),
        spent=(correlated_total(Payment.objects.filter(payer=OuterRef('pk'), status=Payment.Status.SUCCEEDED), 'SUM', 'amount', MONEY)
               + correlated_total(_events_of_customer().filter(status='CONFIRMED'), 'SUM', 'total_amount', MONEY)),
        upcoming_trip=Exists(trips.filter(schedule__starts_at__gte=now)),
        upcoming_event=Exists(events.filter(schedule__starts_at__gte=now)),
        due_trip=Exists(trips.filter(status__in=TRIP_AWAITING)),
        due_event=Exists(_events_of_customer().filter(Q(status='PENDING') & holding)),
    )
    return qs.annotate(booking_count=F('trip_bookings') + F('event_bookings'))


BUCKETS = {
    'upcoming': Q(upcoming_trip=True) | Q(upcoming_event=True),
    'due': Q(due_trip=True) | Q(due_event=True),
    'repeat': Q(booking_count__gte=2),
    'blocked': Q(is_active=False),
}


# ---------- list ----------

class CustomerListView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request):
        resource = _resolve('customers')
        _require_model_permission(request, resource, 'view')
        search = request.query_params.get('search', '').strip()
        bucket = request.query_params.get('status', 'all')
        start, end = date_range(request)

        qs = customer_queryset(request)
        if search:
            qs = qs.filter(Q(full_name__icontains=search) | Q(phone_number__icontains=search) | Q(email__icontains=search))
        qs = with_totals(in_range(qs, 'date_joined', start, end))
        counts = {key: qs.filter(q).count() for key, q in BUCKETS.items()}
        counts['all'] = qs.count()
        if bucket in BUCKETS:
            qs = qs.filter(BUCKETS[bucket])
        qs = qs.order_by(SORTS.get(request.query_params.get('sort', ''), '-date_joined'), '-pk')

        if wants_export(request):
            _access_log(request, resource, purpose='customers export')
            return csv_response(export_filename('customers'), CSV_COLUMNS, customer_rows(list(qs)))
        page, meta = paginate(request, qs)
        _access_log(request, resource, purpose='customers list')
        return Response({**meta, 'counts': counts, 'results': customer_rows(list(page.object_list)),
                         'summary': customer_summary(request)})


def customer_rows(users):
    """Rows for the list. `due` is worked out from payments for this page only (it needs each booking's paid amount)."""
    awaiting = list(Booking.objects.filter(primary_booker__in=users, status__in=TRIP_AWAITING).only('pk', 'primary_booker_id', 'total_amount'))
    paid = paid_by([b.pk for b in awaiting])
    due = {}
    for b in awaiting:
        due[b.primary_booker_id] = due.get(b.primary_booker_id, ZERO) + max(ZERO, b.total_amount - paid[b.pk])
    return [{
        'id': str(u.pk), 'name': u.full_name or '—', 'phone': u.phone_number, 'email': u.email, 'joined': _iso(u.date_joined),
        'trip_bookings': u.trip_bookings, 'event_bookings': u.event_bookings, 'spent': _money(u.spent),
        'due': _money(due.get(u.pk, ZERO)), 'active': u.is_active,
    } for u in users]


def customer_summary(request):
    qs = customer_queryset(request)
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    totals = with_totals(qs)
    return {
        'total': qs.count(),
        'new_month': qs.filter(date_joined__gte=month_start).count(),
        'with_due': totals.filter(BUCKETS['due']).count(),
        'blocked': qs.filter(is_active=False).count(),
    }


# ---------- one customer ----------

def _customer_or_404(request, pk):
    try:
        return customer_queryset(request).get(pk=pk)
    except (ObjectDoesNotExist, ValueError, TypeError):
        raise Http404('Customer not found.')


def note_rows(customer):
    return [{'id': str(n.pk), 'channel': n.channel, 'text': n.summary, 'by': (n.by.full_name or n.by.phone_number) if n.by else '',
             'created_at': _iso(n.created_at)}
            for n in CustomerInteraction.objects.filter(customer=customer).select_related('by').order_by('-created_at')[:50]]


class CustomerDetailView(APIView):
    """One customer with every booking, payment, enquiry and staff note."""
    permission_classes = [StaffOnly]

    def get(self, request, pk):
        _require_model_permission(request, _resolve('customers'), 'view')
        c = _customer_or_404(request, pk)
        trip_rows, event_rows, pay_rows, enquiries = [], [], [], []
        if _can(request, 'bookings'):
            bs = list(Booking.objects.filter(primary_booker=c).select_related('primary_booker', 'schedule').order_by('-created_at'))
            trip_rows = trip_booking_rows(bs, title_map(Trip, {b.schedule.trip_id for b in bs}))
        if _can(request, 'event-registrations'):
            rs = list(EventRegistration.objects.filter(Q(registrant=c) | Q(contact_phone=c.phone_number)).select_related('schedule').order_by('-created_at'))
            event_rows = event_booking_rows(rs, title_map(Event, {r.schedule.event_id for r in rs}), request)
        if _can(request, 'payments'):
            pay_rows = [{'id': str(p.pk), 'amount': _money(p.amount), 'status': p.status, 'kind': p.kind, 'method': p.method,
                         'reference': p.manual_reference, 'created_at': _iso(p.created_at)}
                        for p in Payment.objects.filter(payer=c).exclude(status=Payment.Status.CREATED).order_by('-created_at')]
        if _can(request, 'enquiries'):
            enquiries = [{'id': str(e.pk), 'message': e.message, 'status': e.status, 'created_at': _iso(e.created_at)}
                         for e in Enquiry.objects.filter(phone=c.phone_number).order_by('-created_at')[:20]]
        can_see_notes = staff_has_perm(request, 'crm.view_customerinteraction')
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
            'notes': note_rows(c) if can_see_notes else None,
            'can_edit': _can(request, 'customers', 'change'),
            'can_block': staff_has_perm(request, 'accounts.change_user') and not c.is_staff,
            'can_note': staff_has_perm(request, 'crm.add_customerinteraction'),
        })


# ---------- actions ----------

class BlockSerializer(serializers.Serializer):
    blocked = serializers.BooleanField()
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if attrs['blocked'] and not attrs['reason'].strip():
            raise serializers.ValidationError({'reason': 'Say why, so other staff know.'})
        return attrs


class CustomerBlockView(APIView):
    """Block or unblock a customer. Blocked customers can't sign in or book, and their open sessions stop working."""
    permission_classes = [StaffOnly]

    def post(self, request, pk):
        require_staff_perm(request, 'accounts.change_user', 'You do not have permission to block customers.')
        customer = _customer_or_404(request, pk)
        if customer.is_staff:
            raise ValidationError({'detail': 'This person is a staff member. Deactivate them on the Team & roles page instead.'})
        data = BlockSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        blocked, reason = data.validated_data['blocked'], data.validated_data['reason'].strip()
        if customer.is_active == (not blocked):
            return Response({'active': customer.is_active})   # already in that state
        resource = _resolve('customers')
        with transaction.atomic():
            customer.is_active = not blocked
            customer.save(update_fields=['is_active'])
            CustomerInteraction.objects.create(customer=customer, channel='note', by=request.user,
                                               summary=f'{"Blocked" if blocked else "Unblocked"}{f": {reason}" if reason else ""}')
            _audit(request, 'customers.block' if blocked else 'customers.unblock', resource, customer,
                   before={'is_active': blocked}, after={'is_active': not blocked, 'reason': reason})
        return Response({'active': customer.is_active})


class NoteSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000, trim_whitespace=True)
    channel = serializers.ChoiceField(choices=sorted(NOTE_CHANNELS), default='note')


class CustomerNotesView(APIView):
    permission_classes = [StaffOnly]

    def post(self, request, pk):
        require_staff_perm(request, 'crm.add_customerinteraction', 'You do not have permission to add notes.')
        customer = _customer_or_404(request, pk)
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        CustomerInteraction.objects.create(customer=customer, by=request.user, channel=data.validated_data['channel'],
                                           summary=data.validated_data['text'])
        return Response(note_rows(customer), status=status.HTTP_201_CREATED)
