"""Public event bookings: capacity-checked slot holds that staff confirm.

Capacity = confirmed bookings + pending bookings whose hold has not expired. The schedule row is locked while
counting, so two visitors booking the last slots at the same time cannot both succeed.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from content.models import ContentStatus

from .models import Event, EventRegistration, EventSchedule


def expire_stale_holds(now=None):
    """Mark pending bookings whose hold ran out as EXPIRED (capacity already ignores them; this keeps the admin tidy)."""
    now = now or timezone.now()
    return (EventRegistration.objects
            .filter(status=EventRegistration.Status.PENDING, reserved_until__lte=now)
            .update(status=EventRegistration.Status.EXPIRED, updated_at=now))


def create_event_booking(*, event_slug, schedule_id, name, phone, participant_count, note='', source='website', email=''):
    """Hold `participant_count` places on a published event date. Raises ValidationError with a field dict."""
    from crm.models import Enquiry, EnquirySource

    event = Event.objects.filter(slug=event_slug, status=ContentStatus.PUBLISHED).first()
    if event is None:
        raise ValidationError({'event': 'This event is not open for booking.'})

    with transaction.atomic():
        try:
            schedule = EventSchedule.objects.select_for_update().get(pk=schedule_id, event=event)
        except (EventSchedule.DoesNotExist, ValueError, ValidationError):
            raise ValidationError({'schedule': 'Choose a date belonging to this event.'})
        if schedule.has_started():
            raise ValidationError({'schedule': 'Bookings for this date have closed.'})

        booking = EventRegistration(
            schedule=schedule, contact_name=name, contact_phone=phone, contact_email=email,
            participant_count=participant_count,
            unit_price=event.price, customer_note=note, source=source, status=EventRegistration.Status.PENDING,
        )
        booking.full_clean(exclude=['reference', 'registrant'])   # registration type, per-booking cap, remaining capacity
        for _ in range(5):   # astronomically unlikely, but never surface a reference collision to the visitor
            if not EventRegistration.objects.filter(reference=booking.reference).exists():
                break
            booking.reference = EventRegistration._meta.get_field('reference').default()
        booking.save()

        # Keep the CRM inbox as the team's follow-up queue.
        source_row, _ = EnquirySource.objects.get_or_create(name=source)
        Enquiry.objects.create(
            name=name, phone=phone, email=email, event=event, event_schedule=schedule, group_size=min(participant_count, 30),
            source=source_row, consent_to_contact=True,
            message='\n'.join(filter(None, [
                f'Event booking {booking.reference}: {participant_count} participant(s), total ₹{booking.total_amount}',
                f'Status: pending confirmation (slots held until {timezone.localtime(booking.reserved_until):%d %b %Y %I:%M %p})',
                f'Customer note: {note}' if note else '',
            ])),
        )
    return booking
