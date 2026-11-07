"""Trips, schedules, pricing, capacity, itineraries, pickup points, events (sections 13.3, 3.1-3.3)."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
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
class Event(UUIDModel, Timestamped, Publishable):
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(TripCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='events')
    venue_name = models.CharField(max_length=200, blank=True)
    venue_address = models.TextField(blank=True)
    cover = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    history = HistoricalRecords()

    class Meta:
        db_table = 'events'

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class EventTranslation(TranslationBase):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='translations')

    class Meta:
        db_table = 'event_translations'
        unique_together = ('event', 'language')


class EventSchedule(UUIDModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='schedules')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'event_schedules'
        ordering = ['starts_at']


class EventRegistration(UUIDModel, Timestamped):
    schedule = models.ForeignKey(EventSchedule, on_delete=models.CASCADE, related_name='registrations')
    registrant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='event_registrations')
    status = models.CharField(max_length=12, default='REGISTERED')

    class Meta:
        db_table = 'event_registrations'


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
