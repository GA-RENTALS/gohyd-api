"""Trips, schedules, pricing, capacity, itineraries, pickup points, events (sections 13.3, 3.1-3.3)."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from content.models import Destination, MediaAsset, Publishable, TranslationBase
from core.models import TenantBound, Timestamped, UUIDModel


class TripCategory(Timestamped):
    """Experience categories (Rides, Sports, Food, Culture, Social, Hidden gems, Trekking, Camping, ...)."""
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    name_te = models.CharField(max_length=100, blank=True)
    name_hi = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'trip_categories'
        verbose_name_plural = 'trip categories'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Trip(UUIDModel, Timestamped, Publishable):
    """
    `status` (from Publishable) is the EDITORIAL workflow. `operational_status` is availability and is
    deliberately separate: operational changes must not wait on editorial approval (section 16).
    """
    class Operational(models.TextChoices):
        OPEN = 'OPEN', 'Open for booking'
        SOLD_OUT = 'SOLD_OUT', 'Sold out'
        PAUSED = 'PAUSED', 'Paused'
        CANCELLED = 'CANCELLED', 'Cancelled'
        COMPLETED = 'COMPLETED', 'Completed'

    slug = models.SlugField(unique=True)
    categories = models.ManyToManyField(TripCategory, blank=True, related_name='trips', through='TripCategoryLink')
    destinations = models.ManyToManyField(Destination, blank=True, related_name='trips', through='TripDestination')
    operational_status = models.CharField(max_length=12, choices=Operational.choices, default=Operational.OPEN, db_index=True)
    cover = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    duration_hours = models.PositiveIntegerField(null=True, blank=True)
    difficulty = models.CharField(max_length=20, blank=True)
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    requires_waiver = models.BooleanField(default=True)
    # 3.1 / 3.2: null means "use the global default" (core.Setting); a value overrides it for this trip.
    advance_basis_points = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(10000)],
                                                            help_text='Advance % in basis points (30% = 3000). Blank = global default.')
    balance_due_days_before = models.PositiveSmallIntegerField(null=True, blank=True,
                                                               help_text='Balance must be paid this many days before departure. Blank = global default.')
    gst_configuration = models.ForeignKey('payments.GstConfiguration', null=True, blank=True, on_delete=models.PROTECT, related_name='trips')
    sort_order = models.PositiveIntegerField(default=0)
    history = HistoricalRecords()

    class Meta:
        db_table = 'trips'
        ordering = ['sort_order', '-created_at']

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class TripCategoryLink(TenantBound):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    category = models.ForeignKey(TripCategory, on_delete=models.CASCADE)

    class Meta:
        db_table = 'trip_category_links'
        unique_together = ('trip', 'category')


class TripDestination(TenantBound):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'trip_destinations'
        unique_together = ('trip', 'destination')


class TripTranslation(TranslationBase):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='translations')
    history = HistoricalRecords()

    class Meta:
        db_table = 'trip_translations'
        unique_together = ('trip', 'language')

    def __str__(self):
        return f'{self.trip.slug} [{self.language}] {self.title}'


class TripSchedule(UUIDModel, Timestamped):
    """One departure. Capacity is committed transactionally in bookings.services (select_for_update)."""
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='schedules')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    seats_booked = models.PositiveIntegerField(default=0, help_text='Maintained only inside booking transactions.')
    price_per_participant = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, default='INR')
    is_open = models.BooleanField(default=True, help_text='Operational switch; independent of editorial publishing.')
    balance_due_days_before = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Overrides trip and global value.')
    advance_basis_points = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(10000)])

    class Meta:
        db_table = 'trip_schedules'
        ordering = ['starts_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(seats_booked__lte=models.F('capacity')), name='seats_within_capacity'),
            models.CheckConstraint(condition=models.Q(ends_at__gte=models.F('starts_at')), name='schedule_ends_after_start'),
        ]

    @property
    def seats_left(self):
        return self.capacity - self.seats_booked

    def __str__(self):
        return f'{self.trip.slug} {self.starts_at:%Y-%m-%d}'


class TripPricingRule(Timestamped):
    """trip_pricing: optional modifiers on top of the schedule base price (early-bird, child, group)."""
    schedule = models.ForeignKey(TripSchedule, on_delete=models.CASCADE, related_name='pricing_rules')
    label = models.CharField(max_length=80)
    amount_delta = models.DecimalField(max_digits=12, decimal_places=2, help_text='Negative for a discount.')
    min_participants = models.PositiveSmallIntegerField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'trip_pricing'


class TripItinerary(Timestamped):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='itineraries')
    day_number = models.PositiveSmallIntegerField(default=1)
    title_en = models.CharField(max_length=200)
    title_te = models.CharField(max_length=200, blank=True)
    title_hi = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'trip_itineraries'
        ordering = ['day_number']

    def __str__(self):
        return f'{self.trip.slug} · Day {self.day_number}' + (f' · {self.title_en}' if self.title_en else '')


class TripItineraryItem(TenantBound):
    itinerary = models.ForeignKey(TripItinerary, on_delete=models.CASCADE, related_name='items')
    time_label = models.CharField(max_length=30, blank=True)
    text_en = models.TextField()
    text_te = models.TextField(blank=True)
    text_hi = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'trip_itinerary_items'
        ordering = ['sort_order']


class TripPickupPoint(Timestamped):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='pickup_points')
    pickup_location = models.ForeignKey('operations.PickupLocation', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    pickup_time = models.TimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'trip_pickup_points'
        ordering = ['sort_order', 'pickup_time']

    def __str__(self):
        return f'{self.trip.slug}: {self.name}'


class TripMedia(TenantBound):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='media')
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'trip_media'
        ordering = ['sort_order']


class TripInclusion(TenantBound):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='inclusions')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'trip_inclusions'


class TripExclusion(TenantBound):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='exclusions')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'trip_exclusions'


class TripThingToBring(TenantBound):
    """An item guests should bring on this trip, translated for the public detail page."""
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='things_to_bring')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'trip_things_to_bring'
        ordering = ['sort_order', 'id']


class TripPolicy(Timestamped):
    """Refund policy as tiers: refund_percent if cancelled at least `days_before` days before departure."""
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='policies')
    kind = models.CharField(max_length=20, default='cancellation')
    days_before = models.PositiveSmallIntegerField(help_text='Applies when cancelling >= this many days before departure.')
    refund_basis_points = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10000)])
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'trip_policies'
        ordering = ['-days_before']


class TripAssignment(TenantBound):
    """Organisers / team members responsible for a trip."""
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='assignments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='trip_assignments')
    role = models.CharField(max_length=40, default='organizer')

    class Meta:
        db_table = 'trip_assignments'
        unique_together = ('trip', 'user', 'role')


class TripStatusHistory(UUIDModel):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='status_history')
    field = models.CharField(max_length=30)  # editorial | operational
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'trip_status_history'


# ---- Events (sports, social, food, culture meetups) ----
class EventRegistrationType(models.TextChoices):
    INDIVIDUAL = 'INDIVIDUAL', 'Individual only'
    GROUP = 'GROUP', 'Group only'
    BOTH = 'BOTH', 'Individual and group'


class Event(UUIDModel, Timestamped, Publishable):
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(TripCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    venue_name = models.CharField(max_length=200, blank=True)
    venue_address = models.TextField(blank=True)
    cover = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_featured = models.BooleanField(default=False, db_index=True)
    booking_whatsapp_number = models.CharField(max_length=20, blank=True)
    show_in_popup = models.BooleanField(
        default=False, db_index=True,
        help_text='Show this event in the upcoming-events popup when visitors open the website.')
    popup_banner = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Poster shown in the website popup. Falls back to the cover image when empty.')
    popup_order = models.PositiveIntegerField(default=0, help_text='Lower numbers appear first in the popup.')
    registration_type = models.CharField(max_length=10, choices=EventRegistrationType.choices,
                                         default=EventRegistrationType.BOTH)
    max_participants_per_booking = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)],
        help_text='Optional cap for one booking. Leave empty to allow up to the remaining event capacity.')
    reservation_hold_hours = models.PositiveSmallIntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(720)],
        help_text='How long an unconfirmed (pending) website booking holds its slots before they are released.')
    history = HistoricalRecords()

    class Meta:
        db_table = 'events'

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class EventTranslation(TranslationBase):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='translations')
    headline = models.CharField(max_length=160, blank=True, help_text='About-section heading, e.g. "Play. Connect. Make New Friends."')
    image_caption = models.CharField(max_length=255, blank=True, help_text='Line shown under the cover image.')
    format_note = models.TextField(blank=True, help_text='Paragraph under the Event Format table.')
    schedule_note = models.TextField(blank=True, help_text='Small print under the Event Schedule, e.g. timings may change.')

    class Meta:
        db_table = 'event_translations'
        unique_together = ('event', 'language')

    def __str__(self):
        return f'{self.event.slug} [{self.language}] {self.title}'


class EventItinerary(Timestamped):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='itineraries')
    day_number = models.PositiveSmallIntegerField(default=1)
    title_en = models.CharField(max_length=200)
    title_te = models.CharField(max_length=200, blank=True)
    title_hi = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = 'event_itineraries'
        ordering = ['day_number']

    def __str__(self):
        return f'{self.event.slug} · Day {self.day_number}' + (f' · {self.title_en}' if self.title_en else '')


class EventItineraryItem(TenantBound):
    itinerary = models.ForeignKey(EventItinerary, on_delete=models.CASCADE, related_name='items')
    time_label = models.CharField(max_length=30, blank=True)
    text_en = models.TextField()
    text_te = models.TextField(blank=True)
    text_hi = models.TextField(blank=True)
    detail_en = models.CharField(max_length=255, blank=True, help_text='Optional smaller line under the item.')
    detail_te = models.CharField(max_length=255, blank=True)
    detail_hi = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_itinerary_items'
        ordering = ['sort_order']


class EventThingToBring(TenantBound):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='things_to_bring')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_things_to_bring'
        ordering = ['sort_order', 'id']


class EventInclusion(TenantBound):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='inclusions')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_inclusions'
        ordering = ['sort_order', 'id']


class EventExclusion(TenantBound):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='exclusions')
    text_en = models.CharField(max_length=255)
    text_te = models.CharField(max_length=255, blank=True)
    text_hi = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_exclusions'
        ordering = ['sort_order', 'id']


class EventFormatDetail(TenantBound):
    """One labelled fact in the "Event Format" section, e.g. Match format = Pool play, Overs per match = 10."""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='format_details')
    label_en = models.CharField(max_length=80)
    label_te = models.CharField(max_length=80, blank=True)
    label_hi = models.CharField(max_length=80, blank=True)
    value_en = models.CharField(max_length=160)
    value_te = models.CharField(max_length=160, blank=True)
    value_hi = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_format_details'
        ordering = ['sort_order', 'id']


class EventHighlight(TenantBound):
    """A tick-marked highlight in the About section, e.g. "Organiser-managed teams"."""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='highlights')
    text_en = models.CharField(max_length=160)
    text_te = models.CharField(max_length=160, blank=True)
    text_hi = models.CharField(max_length=160, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_highlights'
        ordering = ['sort_order', 'id']


class EventFAQ(TenantBound):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='faqs')
    question_en = models.CharField(max_length=255)
    question_te = models.CharField(max_length=255, blank=True)
    question_hi = models.CharField(max_length=255, blank=True)
    answer_en = models.TextField()
    answer_te = models.TextField(blank=True)
    answer_hi = models.TextField(blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_faqs'
        ordering = ['sort_order', 'id']
        verbose_name = 'event FAQ'


class EventRule(TenantBound):
    """One line in the "Rules & Guidelines" section."""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='rules')
    text_en = models.CharField(max_length=300)
    text_te = models.CharField(max_length=300, blank=True)
    text_hi = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'event_rules'
        ordering = ['sort_order', 'id']


class EventSchedule(UUIDModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='schedules')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    is_date_locked = models.BooleanField(default=False)
    time_tbd = models.BooleanField(default=False)

    class Meta:
        db_table = 'event_schedules'
        ordering = ['starts_at']

    def __str__(self):
        when = timezone.localtime(self.starts_at)
        label = when.strftime('%d %b %Y') if self.time_tbd else when.strftime('%d %b %Y, %I:%M %p')
        return f'{self.event.slug} · {label}' + (f' · {self.capacity} places' if self.capacity else '')

    def clean(self):
        super().clean()
        if self.pk:
            previous = type(self)._base_manager.filter(pk=self.pk).only(
                'starts_at', 'ends_at', 'is_date_locked',
            ).first()
            if previous and previous.is_date_locked:
                if not self.is_date_locked:
                    raise ValidationError({'is_date_locked': 'A locked event date cannot be unlocked.'})
                if timezone.localtime(previous.starts_at).date() != timezone.localtime(self.starts_at).date():
                    raise ValidationError({'starts_at': 'This event date is locked and cannot be changed.'})
                old_end_date = timezone.localtime(previous.ends_at).date() if previous.ends_at else None
                new_end_date = timezone.localtime(self.ends_at).date() if self.ends_at else None
                start_date = timezone.localtime(self.starts_at).date()
                adding_same_day_end = old_end_date is None and new_end_date == start_date
                if old_end_date != new_end_date and not adding_same_day_end:
                    raise ValidationError({'ends_at': 'This event date is locked and cannot be changed.'})
        if self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({'ends_at': 'The end time must be after the start time.'})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def has_started(self, now=None):
        now = now or timezone.now()
        if self.time_tbd:
            return timezone.localtime(self.starts_at).date() < timezone.localtime(now).date()
        return self.starts_at <= now

    def reserved_count(self, now=None, exclude_pk=None):
        """Places taken by confirmed bookings plus pending bookings whose hold has not expired."""
        qs = EventRegistration.holding(now).filter(schedule=self)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        return qs.aggregate(n=models.Sum('participant_count'))['n'] or 0

    def confirmed_count(self):
        return (self.registrations.filter(status=EventRegistration.Status.CONFIRMED)
                .aggregate(n=models.Sum('participant_count'))['n'] or 0)

    def seats_left(self, now=None):
        if self.capacity is None:
            return None
        return max(self.capacity - self.reserved_count(now), 0)


def _new_event_reference():
    import secrets
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'   # no 0/O/1/I/L
    return 'GHE-' + ''.join(secrets.choice(alphabet) for _ in range(6))


class EventRegistration(UUIDModel, Timestamped):
    """One event booking (individual or group). Pending bookings hold slots until `reserved_until`; only staff confirm them."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending confirmation'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        EXPIRED = 'EXPIRED', 'Expired (hold released)'

    reference = models.CharField(max_length=16, unique=True, editable=False, default=_new_event_reference)
    schedule = models.ForeignKey(EventSchedule, on_delete=models.PROTECT, related_name='registrations')
    registrant = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='event_registrations')
    contact_name = models.CharField(max_length=150, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True, db_index=True)
    contact_email = models.EmailField(blank=True)
    participant_count = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                     help_text='Price per participant when booked. Filled from the event price if empty.')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    reserved_until = models.DateTimeField(null=True, blank=True,
                                          help_text='Pending bookings stop holding slots after this time.')
    source = models.CharField(max_length=20, default='website')
    customer_note = models.TextField(blank=True)
    staff_note = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = 'event_registrations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference} · {self.contact_name or "booking"} × {self.participant_count}'

    @classmethod
    def holding(cls, now=None):
        """Bookings that currently take up capacity."""
        now = now or timezone.now()
        return cls.objects.filter(
            models.Q(status=cls.Status.CONFIRMED)
            | models.Q(status=cls.Status.PENDING, reserved_until__gt=now)
            | models.Q(status=cls.Status.PENDING, reserved_until__isnull=True)
        )

    @property
    def is_holding(self):
        if self.status == self.Status.CONFIRMED:
            return True
        return self.status == self.Status.PENDING and (self.reserved_until is None or self.reserved_until > timezone.now())

    @property
    def effective_status(self):
        """PENDING bookings whose hold ran out read as EXPIRED even before the row is updated."""
        if self.status == self.Status.PENDING and self.reserved_until and self.reserved_until <= timezone.now():
            return self.Status.EXPIRED
        return self.status

    def clean(self):
        super().clean()
        if not self.schedule_id:
            return
        from django.db import transaction
        schedule = self.schedule
        if transaction.get_connection().in_atomic_block:
            schedule = EventSchedule.objects.select_for_update().get(pk=self.schedule_id)
        event = schedule.event
        if event.registration_type == EventRegistrationType.INDIVIDUAL and self.participant_count != 1:
            raise ValidationError({'participant_count': 'This event accepts individual registrations only.'})
        if event.registration_type == EventRegistrationType.GROUP and self.participant_count < 2:
            raise ValidationError({'participant_count': 'This event accepts group registrations only (2 or more).'})
        if event.max_participants_per_booking and self.participant_count > event.max_participants_per_booking:
            raise ValidationError({'participant_count': f'One booking can include at most {event.max_participants_per_booking} participants.'})
        if self.is_holding and schedule.capacity is not None:
            left = schedule.capacity - schedule.reserved_count(exclude_pk=self.pk)
            if self.participant_count > left:
                raise ValidationError({'participant_count': (
                    f'Only {max(left, 0)} slot{"" if left == 1 else "s"} left for this date.' if left > 0
                    else 'This date is fully booked.')})

    def save(self, *args, **kwargs):
        now = timezone.now()
        if self.contact_phone:
            # Staff may type '98765 43210'; store '+919876543210' so the visitor's status lookup matches.
            from accounts.models import normalize_phone
            try:
                self.contact_phone = normalize_phone(self.contact_phone)
            except ValidationError:
                pass
        if self.unit_price is None and self.schedule_id:
            self.unit_price = self.schedule.event.price
        self.total_amount = (self.unit_price or 0) * self.participant_count
        if self.status == self.Status.PENDING and self.reserved_until is None and self.schedule_id:
            from datetime import timedelta
            # Hold for the configured time, but never past the event start.
            self.reserved_until = min(now + timedelta(hours=self.schedule.event.reservation_hold_hours),
                                      max(self.schedule.starts_at, now + timedelta(minutes=30)))
        if self.status == self.Status.CONFIRMED and not self.confirmed_at:
            self.confirmed_at = now
        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            self.cancelled_at = now
        return super().save(*args, **kwargs)


class EventParticipant(UUIDModel):
    registration = models.ForeignKey(EventRegistration, on_delete=models.CASCADE, related_name='participants')
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = 'event_participants'


class EventAttendance(UUIDModel):
    participant = models.ForeignKey(EventParticipant, on_delete=models.CASCADE, related_name='attendance')
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    method = models.CharField(max_length=10, default='QR')

    class Meta:
        db_table = 'event_attendance'
