"""One-page overview of a trip or an event: headline numbers, bookings, payments and participants.

Numbers reuse the booking rules already in the codebase:
- trip "paid" money = successful payment allocations (bookings.services.paid_amount), refunds as in refunded_amount;
- event bookings have no payment rows, so a CONFIRMED booking counts as paid and PENDING as awaiting payment.
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking, BookingParticipant
from payments.models import Payment, PaymentAllocation, PaymentKind, Refund
from payments.services import amounts_due
from trips.models import Event, EventRegistration, EventSchedule, Trip, TripSchedule

from .permissions import StaffOnly, staff_has_perm
from .views import _access_log, _require_model_permission, _resolve

ZERO = Decimal('0.00')
REFUND_COUNTED = [Refund.Status.PROCESSED, Refund.Status.PROCESSING, Refund.Status.APPROVED]   # same as bookings.services.refunded_amount


def _money(v):
    return str((v or ZERO).quantize(Decimal('0.01')))


def _iso(v):
    return v.isoformat() if v else None


def _title(obj):
    """English title from the translation table, falling back to the slug."""
    row = obj.translations.filter(language='en').only('title').first() or obj.translations.only('title').first()
    return row.title if row else obj.slug.replace('-', ' ').title()


def _cover(obj, request):
    asset = getattr(obj, 'cover', None)
    if not asset or not asset.file:
        return None
    try:
        return request.build_absolute_uri(asset.file.url)
    except (ValueError, OSError):
        return None


def _can(request, key, action='view'):
    try:
        _require_model_permission(request, _resolve(key), action)
        return True
    except Exception:   # noqa: BLE001 - PermissionDenied: just hide that part of the page
        return False


def _get(model, pk):
    try:
        return model.objects.get(pk=pk)
    except (model.DoesNotExist, ValueError, TypeError, Exception):   # noqa: BLE001 - bad UUIDs raise ValidationError
        raise Http404('Record not found.')


class TripOverviewView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request, pk):
        _require_model_permission(request, _resolve('trips'), 'view')
        trip = _get(Trip, pk)
        schedule_id = request.query_params.get('schedule') or None

        schedules = list(TripSchedule.objects.filter(trip=trip).order_by('starts_at'))
        bookings_qs = Booking.objects.filter(schedule__trip=trip).select_related('primary_booker', 'schedule').order_by('-created_at')
        if schedule_id:
            bookings_qs = bookings_qs.filter(schedule_id=schedule_id)
        can_bookings = _can(request, 'bookings')
        can_payments = _can(request, 'payments')
        bookings = list(bookings_qs) if can_bookings else []
        ids = [b.pk for b in bookings]

        paid_by = defaultdict(lambda: ZERO)
        for row in (PaymentAllocation.objects.filter(booking_id__in=ids, payment__status=Payment.Status.SUCCEEDED)
                    .values('booking_id').annotate(t=Sum('amount'))):
            paid_by[row['booking_id']] = row['t'] or ZERO
        refunded_by = defaultdict(lambda: ZERO)
        for row in Refund.objects.filter(booking_id__in=ids, status__in=REFUND_COUNTED).values('booking_id').annotate(t=Sum('amount')):
            refunded_by[row['booking_id']] = row['t'] or ZERO

        active = [b for b in bookings if b.status != Booking.Status.CANCELLED]
        paid_statuses = {Booking.Status.FULLY_PAID, Booking.Status.COMPLETED}
        stats = {
            'registrations': len(active),
            'paid': sum(1 for b in active if b.status in paid_statuses),
            'pending': sum(1 for b in active if b.status in {Booking.Status.PENDING_ADVANCE, Booking.Status.CONFIRMED}),
            'cancelled': len(bookings) - len(active),
            'participants': sum(b.participant_count for b in active),
            'revenue': _money(sum((paid_by[b.pk] - refunded_by[b.pk] for b in bookings), ZERO)),
            'outstanding': _money(sum((max(ZERO, b.total_amount - paid_by[b.pk]) for b in active), ZERO)),
        }

        registrations = []
        for b in bookings:
            outstanding = ZERO if b.status == Booking.Status.CANCELLED else max(ZERO, b.total_amount - paid_by[b.pk])
            advance_due = amounts_due([b], PaymentKind.ADVANCE).get(b.pk, ZERO) if outstanding else ZERO
            registrations.append({
                'id': str(b.pk), 'reference': b.reference, 'status': b.status, 'status_label': b.get_status_display(),
                'name': b.primary_booker.full_name or b.primary_booker.phone_number, 'phone': b.primary_booker.phone_number,
                'schedule_id': str(b.schedule_id), 'starts_at': _iso(b.schedule.starts_at),
                'participants': b.participant_count, 'total': _money(b.total_amount), 'paid': _money(paid_by[b.pk]),
                'outstanding': _money(outstanding), 'advance_due': _money(advance_due),
                'checkout_id': str(b.checkout_id), 'created_at': _iso(b.created_at),
            })

        # Every payment for this trip's bookings (newest first). Pending manual ones get Verify / Reject in the UI.
        payments = []
        if can_payments and ids:
            for p in (Payment.objects.filter(allocations__booking_id__in=ids)
                      .select_related('payer').prefetch_related('allocations__booking').distinct().order_by('-created_at')):
                payments.append({
                    'id': str(p.pk), 'amount': _money(p.amount), 'kind': p.kind, 'method': p.method, 'status': p.status,
                    'reference': p.manual_reference, 'payer': p.payer.full_name or p.payer.phone_number, 'created_at': _iso(p.created_at),
                    'bookings': sorted({a.booking.reference for a in p.allocations.all()}),
                })
        pending_payments = [p for p in payments if p['status'] == Payment.Status.PENDING_VERIFICATION]

        participants = []
        if _can(request, 'participants'):
            for p in BookingParticipant.objects.filter(booking_id__in=[b.pk for b in active]).select_related('booking').order_by('booking__created_at', 'full_name'):
                participants.append({
                    'id': str(p.pk), 'name': p.full_name, 'phone': p.phone, 'age': p.age, 'booking': p.booking.reference,
                    'emergency_contact': ' · '.join(filter(None, [p.emergency_contact_name, p.emergency_contact_phone])),
                    'waiver': bool(p.waiver_accepted_at), 'checked_in_at': _iso(p.checked_in_at),
                })

        _access_log(request, _resolve('bookings'), purpose='trip overview')
        return Response({
            'kind': 'trip', 'id': str(trip.pk), 'slug': trip.slug, 'title': _title(trip),
            'status': trip.status, 'operational_status': trip.operational_status, 'operational_label': trip.get_operational_status_display(),
            'schedules': [{
                'id': str(s.pk), 'starts_at': _iso(s.starts_at), 'ends_at': _iso(s.ends_at), 'capacity': s.capacity,
                'booked': s.seats_booked, 'price': _money(s.price_per_participant), 'is_open': s.is_open,
            } for s in schedules],
            'schedule': schedule_id, 'stats': stats, 'registrations': registrations,
            'pending_payments': pending_payments, 'payments': payments, 'participants': participants,
            'cover_url': _cover(trip, request),
            'permissions': {'bookings': can_bookings, 'payments': can_payments, 'participants': _can(request, 'participants'),
                            'cancel': request.user.has_perm('bookings.change_booking'),
                            'record_payment': request.user.has_perm('payments.add_payment'),
                            'verify_payment': staff_has_perm(request, 'payments.change_payment'),
                            'check_in': _can(request, 'participants', 'change'),
                            'edit': _can(request, 'trips', 'change'),
                            'delete': _can(request, 'trips', 'delete')},
        })


class EventOverviewView(APIView):
    permission_classes = [StaffOnly]

    def get(self, request, pk):
        _require_model_permission(request, _resolve('events'), 'view')
        event = _get(Event, pk)
        schedule_id = request.query_params.get('schedule') or None
        now = timezone.now()

        schedules = list(EventSchedule.objects.filter(event=event).order_by('starts_at'))
        can_regs = _can(request, 'event-registrations')
        regs_qs = EventRegistration.objects.filter(schedule__event=event).select_related('schedule').prefetch_related('participants__attendance').order_by('-created_at')
        if schedule_id:
            regs_qs = regs_qs.filter(schedule_id=schedule_id)
        regs = list(regs_qs) if can_regs else []

        def status_of(r):
            return r.effective_status   # pending holds that ran out read as EXPIRED

        confirmed = [r for r in regs if status_of(r) == EventRegistration.Status.CONFIRMED]
        pending = [r for r in regs if status_of(r) == EventRegistration.Status.PENDING]
        stats = {
            'registrations': len(confirmed) + len(pending),
            'paid': len(confirmed),
            'pending': len(pending),
            'pending_with_proof': sum(1 for r in pending if r.payment_screenshot or r.payment_utr),
            'cancelled': sum(1 for r in regs if status_of(r) in {EventRegistration.Status.CANCELLED, EventRegistration.Status.EXPIRED}),
            'participants': sum(r.participant_count for r in confirmed + pending),
            'revenue': _money(sum((r.total_amount for r in confirmed), ZERO)),
            'outstanding': _money(sum((r.total_amount for r in pending), ZERO)),
        }

        def proof_url(r):
            if not r.payment_screenshot:
                return None
            try:
                return request.build_absolute_uri(r.payment_screenshot.url)
            except (ValueError, OSError):
                return None

        registrations = [{
            'id': str(r.pk), 'reference': r.reference, 'status': status_of(r),
            'status_label': EventRegistration.Status(status_of(r)).label,
            'name': r.contact_name or '—', 'phone': r.contact_phone, 'email': r.contact_email,
            'schedule_id': str(r.schedule_id), 'starts_at': _iso(r.schedule.starts_at),
            'participants': r.participant_count, 'total': _money(r.total_amount),
            'paid': _money(r.total_amount if status_of(r) == EventRegistration.Status.CONFIRMED else ZERO),
            'outstanding': _money(r.total_amount if status_of(r) == EventRegistration.Status.PENDING else ZERO),
            'payment_proof_url': proof_url(r), 'payment_utr': r.payment_utr,
            'reserved_until': _iso(r.reserved_until), 'customer_note': r.customer_note, 'created_at': _iso(r.created_at),
        } for r in regs]

        # Named attendees where they exist; otherwise the booking's contact person stands in for the group.
        participants = []
        for r in confirmed + pending:
            named = list(r.participants.all())
            if named:
                for p in named:
                    seen = next(iter(p.attendance.all()), None)
                    participants.append({'id': str(p.pk), 'registration_id': str(r.pk), 'name': p.full_name, 'phone': p.phone,
                                         'booking': r.reference, 'group_size': None, 'booking_status': status_of(r),
                                         'checked_in_at': _iso(seen.checked_in_at) if seen else None})
            else:
                participants.append({'id': None, 'registration_id': str(r.pk), 'name': r.contact_name or '—', 'phone': r.contact_phone,
                                     'booking': r.reference, 'group_size': r.participant_count, 'booking_status': status_of(r),
                                     'checked_in_at': None})

        _access_log(request, _resolve('event-registrations'), purpose='event overview')
        return Response({
            'kind': 'event', 'id': str(event.pk), 'slug': event.slug, 'title': _title(event),
            'status': event.status, 'price': _money(event.price), 'venue': event.venue_name,
            'schedules': [{
                'id': str(s.pk), 'starts_at': _iso(s.starts_at), 'ends_at': _iso(s.ends_at), 'capacity': s.capacity,
                'booked': s.reserved_count(now), 'is_open': not s.has_started(now),
            } for s in schedules],
            'schedule': schedule_id, 'stats': stats, 'registrations': registrations,
            'pending_payments': [], 'payments': [], 'participants': participants,
            'cover_url': _cover(event, request),
            'permissions': {'bookings': can_regs, 'payments': False, 'participants': can_regs,
                            'confirm': _can(request, 'event-registrations', 'change'),
                            'cancel': _can(request, 'event-registrations', 'change'),
                            'check_in': _can(request, 'event-attendance', 'change'),
                            'edit': _can(request, 'events', 'change'),
                            'delete': _can(request, 'events', 'delete')},
        })


class CatalogView(APIView):
    """Card list of all trips or events with the numbers staff look at first."""
    permission_classes = [StaffOnly]

    def get(self, request, kind):
        is_trip = kind == 'trips'
        if kind not in ('trips', 'events'):
            raise Http404()
        _require_model_permission(request, _resolve(kind), 'view')
        now = timezone.now()
        model = Trip if is_trip else Event
        q = request.query_params.get('search', '').strip()
        objs = model.objects.select_related('cover').prefetch_related('translations', 'schedules').order_by('-created_at')
        if q:
            from django.db.models import Q
            objs = objs.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()
        objs = list(objs[:200])
        ids = [o.pk for o in objs]

        stats = defaultdict(lambda: {'bookings': 0, 'pending': 0, 'revenue': ZERO})
        if is_trip:
            if _can(request, 'bookings'):
                for b in Booking.objects.filter(schedule__trip_id__in=ids).exclude(status=Booking.Status.CANCELLED).values('schedule__trip_id', 'status'):
                    row = stats[b['schedule__trip_id']]
                    row['bookings'] += 1
                    row['pending'] += b['status'] in (Booking.Status.PENDING_ADVANCE, Booking.Status.CONFIRMED)
                for r in (PaymentAllocation.objects.filter(booking__schedule__trip_id__in=ids, payment__status=Payment.Status.SUCCEEDED)
                          .values('booking__schedule__trip_id').annotate(t=Sum('amount'))):
                    stats[r['booking__schedule__trip_id']]['revenue'] += r['t'] or ZERO
        elif _can(request, 'event-registrations'):
            for r in EventRegistration.objects.filter(schedule__event_id__in=ids).select_related('schedule'):
                st = r.effective_status
                row = stats[r.schedule.event_id]
                if st in (EventRegistration.Status.CONFIRMED, EventRegistration.Status.PENDING):
                    row['bookings'] += 1
                row['pending'] += st == EventRegistration.Status.PENDING
                if st == EventRegistration.Status.CONFIRMED:
                    row['revenue'] += r.total_amount

        def title(o):
            rows = list(o.translations.all())
            en = next((t for t in rows if t.language == 'en'), rows[0] if rows else None)
            return en.title if en else o.slug.replace('-', ' ').title()

        items = []
        for o in objs:
            dates = sorted(o.schedules.all(), key=lambda s: s.starts_at)
            upcoming = [d for d in dates if d.starts_at >= now]
            nxt = upcoming[0] if upcoming else None
            booked = (nxt.seats_booked if is_trip else nxt.reserved_count(now)) if nxt else None
            row = stats[o.pk]
            items.append({
                'id': str(o.pk), 'slug': o.slug, 'title': title(o), 'status': o.status, 'cover_url': _cover(o, request),
                'operational_label': o.get_operational_status_display() if is_trip else None,
                'price': _money(nxt.price_per_participant if is_trip and nxt else getattr(o, 'price', None)),
                'next_date': _iso(nxt.starts_at) if nxt else None, 'next_capacity': nxt.capacity if nxt else None, 'next_booked': booked,
                'dates': len(dates), 'upcoming_dates': len(upcoming),
                'bookings': row['bookings'], 'pending': row['pending'], 'revenue': _money(row['revenue']),
            })
        return Response({'results': items, 'can_create': _can(request, kind, 'add')})
