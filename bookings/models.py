"""Cart, checkout, bookings, participants, seats (sections 3.3, 3.4, 13.4). One checkout -> many bookings; never several trips in one booking row."""
import secrets

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.models import TenantBound, Timestamped, UUIDModel

MONEY = dict(max_digits=12, decimal_places=2)
REF_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def new_reference(prefix='GH'):
    return f'{prefix}-' + ''.join(secrets.choice(REF_ALPHABET) for _ in range(7))


class Cart(UUIDModel, Timestamped):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')

    class Meta:
        db_table = 'carts'


class CartItem(UUIDModel, Timestamped):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.CASCADE, related_name='+')
    participant_count = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    pickup_point = models.ForeignKey('trips.TripPickupPoint', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'cart_items'
        unique_together = ('cart', 'schedule')


class CheckoutOrder(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        PENDING = 'PENDING'
        PARTIALLY_PAID = 'PARTIALLY_PAID'
        PAID = 'PAID'
        EXPIRED = 'EXPIRED'
        CANCELLED = 'CANCELLED'

    reference = models.CharField(max_length=20, unique=True, default=new_reference)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='checkouts')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    currency = models.CharField(max_length=3, default='INR')
    total_amount = models.DecimalField(**MONEY)
    advance_total = models.DecimalField(**MONEY)
    idempotency_key = models.CharField(max_length=80, unique=True)
    coupon = models.ForeignKey('crm.Coupon', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    discount_total = models.DecimalField(default=0, **MONEY)

    class Meta:
        db_table = 'checkout_orders'
        ordering = ['-created_at']


class CheckoutItem(UUIDModel):
    checkout = models.ForeignKey(CheckoutOrder, on_delete=models.CASCADE, related_name='items')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.PROTECT, related_name='+')
    participant_count = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    pickup_point = models.ForeignKey('trips.TripPickupPoint', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    advance_basis_points = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'checkout_items'


class Booking(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        PENDING_ADVANCE = 'PENDING_ADVANCE', 'Awaiting advance'
        CONFIRMED = 'CONFIRMED', 'Confirmed (balance due)'
        FULLY_PAID = 'FULLY_PAID', 'Fully paid'
        CANCELLED = 'CANCELLED'
        COMPLETED = 'COMPLETED'
        NO_SHOW = 'NO_SHOW'

    reference = models.CharField(max_length=20, unique=True, default=new_reference)
    checkout = models.ForeignKey(CheckoutOrder, on_delete=models.PROTECT, related_name='bookings')
    checkout_item = models.OneToOneField(CheckoutItem, on_delete=models.PROTECT, related_name='booking')
    primary_booker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bookings')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.PROTECT, related_name='bookings')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING_ADVANCE, db_index=True)
    participant_count = models.PositiveSmallIntegerField()
    # --- snapshots: never recalculated from live settings (3.3, 3.5) ---
    currency = models.CharField(max_length=3, default='INR')
    unit_price = models.DecimalField(**MONEY)
    subtotal = models.DecimalField(**MONEY, help_text='Net of tax.')
    tax_amount = models.DecimalField(**MONEY)
    total_amount = models.DecimalField(**MONEY)
    advance_basis_points = models.PositiveSmallIntegerField()
    advance_amount = models.DecimalField(**MONEY)
    balance_amount = models.DecimalField(**MONEY)
    balance_due_at = models.DateTimeField(db_index=True)
    tax_snapshot = models.JSONField(default=dict)
    refund_policy_snapshot = models.JSONField(default=list)
    pickup_point = models.ForeignKey('trips.TripPickupPoint', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # --- departure clearance (3.2): unpaid balance needs an audited exception ---
    departure_exception_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    departure_exception_reason = models.CharField(max_length=255, blank=True)
    departure_exception_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'bookings'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'balance_due_at'])]
        permissions = [('grant_departure_exception', 'Can clear a participant to depart with an unpaid balance')]
        constraints = [
            models.CheckConstraint(condition=models.Q(advance_amount__gte=0, balance_amount__gte=0), name='booking_split_nonneg'),
            models.CheckConstraint(condition=models.Q(advance_amount__lte=models.F('total_amount')), name='booking_advance_lte_total'),
        ]

    def __str__(self):
        return self.reference


class BookingItem(TenantBound):
    """Price lines inside one booking (base seats, add-ons, discounts)."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=200)
    quantity = models.PositiveSmallIntegerField(default=1)
    unit_amount = models.DecimalField(**MONEY)

    class Meta:
        db_table = 'booking_items'


class BookingParticipant(UUIDModel, Timestamped):
    """Participants are NOT user accounts (3.4). Stored separately from the customer account."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='participants')
    full_name = models.CharField(max_length=150)
    age = models.PositiveSmallIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    emergency_contact_name = models.CharField(max_length=150, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    medical_notes = models.TextField(blank=True)
    waiver_accepted_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'booking_participants'


class ParticipantPickupAssignment(TenantBound):
    participant = models.ForeignKey(BookingParticipant, on_delete=models.CASCADE, related_name='pickups')
    pickup_point = models.ForeignKey('trips.TripPickupPoint', on_delete=models.PROTECT, related_name='+')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'participant_pickup_assignments'


class BookingStatusHistory(UUIDModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='status_history')
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_status_history'
        ordering = ['created_at']


class BookingSeatAllocation(UUIDModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='seat_allocations')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.PROTECT, related_name='seat_allocations')
    seats = models.PositiveSmallIntegerField()
    released_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_seat_allocations'


class BookingCancellation(UUIDModel):
    booking = models.OneToOneField(Booking, on_delete=models.PROTECT, related_name='cancellation')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.CharField(max_length=255, blank=True)
    refund_basis_points = models.PositiveSmallIntegerField(default=0)
    refund_amount = models.DecimalField(default=0, **MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_cancellations'


class BookingModification(UUIDModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='modifications')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    summary = models.CharField(max_length=255)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_modifications'


class BookingConfirmation(UUIDModel):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='confirmation')
    confirmed_at = models.DateTimeField(auto_now_add=True)
    sent_via = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = 'booking_confirmations'
