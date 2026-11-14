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


def is_bookable(event):
    """Online booking needs a price, unless the event is marked free (price ₹0 means "not announced yet")."""
    return event.is_free or event.price > 0


def create_event_booking(*, event_slug, schedule_id, name, phone, participant_count, note='', source='website', email='',
                         coupon_code=''):
    """Hold `participant_count` places on a published event date. Raises ValidationError with a field dict."""
    from bookings.coupons import CouponError, check_event_coupon, event_discount, find_coupon
    from crm.models import Enquiry, EnquirySource

    event = Event.objects.filter(slug=event_slug, status=ContentStatus.PUBLISHED).first()
    if event is None:
        raise ValidationError({'event': 'This event is not open for booking.'})
    if not is_bookable(event):
        raise ValidationError({'event': 'Bookings open once the price is announced. Message us on WhatsApp to register your interest.'})

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
            refund_policy_snapshot=event.refund_tiers(),   # later policy changes don't affect this booking
        )
        if coupon_code:
            try:
                coupon = find_coupon(coupon_code, lock=True)   # row lock: two bookings can't both take the last use
                check_event_coupon(coupon, event, phone)
            except CouponError as exc:
                raise ValidationError({'coupon': exc.message})
            booking.coupon = coupon
            booking.discount_amount = event_discount(coupon, event.price * participant_count)
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
                f'Event booking {booking.reference}: {participant_count} participant(s), total ₹{booking.total_amount}'
                + (f' after coupon {booking.coupon.code} (−₹{booking.discount_amount})' if booking.coupon else ''),
                f'Status: pending confirmation (slots held until {timezone.localtime(booking.reserved_until):%d %b %Y %I:%M %p})',
                f'Customer note: {note}' if note else '',
            ])),
        )
    return booking


def cancel_event_booking(booking, *, reason=''):
    """The customer cancels their own booking. Frees the places; a paid booking gets a refund by the event's policy
    (recorded as due for staff to send by UPI). Raises ValidationError with a field dict."""
    with transaction.atomic():
        booking = (EventRegistration.objects.select_for_update(of=('self',)).select_related('schedule__event')
                   .get(pk=booking.pk))
        if not booking.can_customer_cancel():
            if booking.effective_status not in (EventRegistration.Status.PENDING, EventRegistration.Status.CONFIRMED):
                raise ValidationError({'detail': 'This booking is no longer active.'})
            raise ValidationError({'detail': 'Online cancellation has closed for this event. Message us on WhatsApp.'})
        booking._refund_basis_points, _ = booking.refund_quote()
        booking.status = EventRegistration.Status.CANCELLED
        booking.cancelled_by_customer = True
        booking.cancel_reason = (reason or '').strip()[:255]
        booking.save()
    return booking


PAYMENT_SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024


class PaymentStorageError(Exception):
    """The screenshot was fine but file storage (S3) refused it."""
_PAYMENT_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}


def submit_payment_proof(*, reference, phone, screenshot, utr=''):
    """Attach the customer's UPI payment screenshot to their pending booking and alert the organiser on WhatsApp.

    The phone number used to book must match. Uploading again replaces the earlier screenshot (and alerts again).
    Raises ValidationError with a field dict.
    """
    from PIL import Image, UnidentifiedImageError

    from core.services import emit

    if screenshot is None:
        raise ValidationError({'screenshot': 'Choose the screenshot of your payment.'})
    if screenshot.size > PAYMENT_SCREENSHOT_MAX_BYTES:
        raise ValidationError({'screenshot': 'The screenshot must be smaller than 5 MB.'})
    try:   # check it really is an image, whatever its name says
        with Image.open(screenshot) as img:
            img.verify()
            fmt = img.format
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ValidationError({'screenshot': 'Upload a JPG, PNG or WebP image of your payment.'})
    if fmt not in _PAYMENT_FORMATS:
        raise ValidationError({'screenshot': 'Upload a JPG, PNG or WebP image of your payment.'})
    screenshot.seek(0)
    screenshot.name = f'payment.{_PAYMENT_FORMATS[fmt]}'

    with transaction.atomic():
        booking = (EventRegistration.objects.select_for_update().select_related('schedule__event')
                   .filter(reference=(reference or '').strip().upper(), contact_phone=phone).first())
        if booking is None:
            raise ValidationError({'detail': 'No booking matches that reference and phone number.'})
        if not (booking.schedule.event.payment_qr_id or booking.schedule.event.payment_upi_id):
            raise ValidationError({'detail': 'This event does not take payment by QR code.'})
        if booking.effective_status not in (EventRegistration.Status.PENDING, EventRegistration.Status.CONFIRMED):
            raise ValidationError({'detail': 'This booking is no longer active, so a payment can\'t be added. Please book again.'})
        old = booking.payment_screenshot.name if booking.payment_screenshot else ''
        try:
            booking.payment_screenshot.save(screenshot.name, screenshot, save=False)
        except Exception as exc:   # noqa: BLE001 - S3/network/credentials: storage backends raise many types
            import logging
            logging.getLogger(__name__).exception('Could not store payment screenshot for %s', booking.reference)
            raise PaymentStorageError() from exc
        booking.payment_utr = (utr or '').strip()[:40]
        booking.payment_submitted_at = timezone.now()
        booking.save(update_fields=['payment_screenshot', 'payment_utr', 'payment_submitted_at', 'updated_at'])
        emit('event_booking.payment_submitted', booking.pk, {'reference': booking.reference})
    if old:
        try:
            booking.payment_screenshot.storage.delete(old)
        except Exception:  # noqa: BLE001 - a leftover file is harmless
            pass
    return booking
