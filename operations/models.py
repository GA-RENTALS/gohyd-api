"""Vendors, vehicles, drivers, pickups, safety (sections 13.8, 13.9)."""
from django.conf import settings
from django.db import models

from core.models import TenantBound, Timestamped, UUIDModel

MONEY = dict(max_digits=12, decimal_places=2)


class Vendor(UUIDModel, Timestamped):
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=40, blank=True, help_text='transport, stay, activity, food, equipment...')
    gstin = models.CharField(max_length=15, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'vendors'

    def __str__(self):
        return self.name


class VendorContact(TenantBound):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = 'vendor_contacts'


class VendorService(TenantBound):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=150)

    class Meta:
        db_table = 'vendor_services'


class VendorContract(Timestamped):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='contracts')
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    terms = models.TextField(blank=True)
    document = models.FileField(upload_to='vendor_contracts/', blank=True)

    class Meta:
        db_table = 'vendor_contracts'


class VendorPricing(TenantBound):
    service = models.ForeignKey(VendorService, on_delete=models.CASCADE, related_name='pricing')
    unit = models.CharField(max_length=40, default='per trip')
    rate = models.DecimalField(**MONEY)
    valid_from = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'vendor_pricing'


class VendorDocument(Timestamped):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=120)
    file = models.FileField(upload_to='vendor_docs/')
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'vendor_documents'


class VendorTripAssignment(TenantBound):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='trip_assignments')
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.CASCADE, related_name='vendor_assignments')
    service = models.ForeignKey(VendorService, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    agreed_amount = models.DecimalField(null=True, blank=True, **MONEY)

    class Meta:
        db_table = 'vendor_trip_assignments'


class Vehicle(UUIDModel, Timestamped):
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name='vehicles')
    registration_number = models.CharField(max_length=20, unique=True)
    kind = models.CharField(max_length=40, blank=True)
    seats = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'vehicles'

    def __str__(self):
        return self.registration_number


class VehicleDocument(Timestamped):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=80)     # RC, insurance, permit, fitness
    file = models.FileField(upload_to='vehicle_docs/')
    expires_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'vehicle_documents'


class Driver(UUIDModel, Timestamped):
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.SET_NULL, related_name='drivers')
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    licence_number = models.CharField(max_length=30, blank=True)
    licence_expires_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'drivers'

    def __str__(self):
        return self.full_name


class TripVehicleAssignment(TenantBound):
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.CASCADE, related_name='vehicle_assignments')
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name='assignments')

    class Meta:
        db_table = 'trip_vehicle_assignments'
        unique_together = ('schedule', 'vehicle')


class TripDriverAssignment(TenantBound):
    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.CASCADE, related_name='driver_assignments')
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name='assignments')
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'trip_driver_assignments'
        unique_together = ('schedule', 'driver')


class PickupLocation(Timestamped):
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        db_table = 'pickup_locations'

    def __str__(self):
        return self.name


# ---- Safety ----
class SafetyChecklist(Timestamped):
    name = models.CharField(max_length=150)
    items = models.JSONField(default=list, help_text='List of check items.')

    class Meta:
        db_table = 'safety_checklists'


class SafetyWaiver(Timestamped):
    title = models.CharField(max_length=200)
    version = models.PositiveSmallIntegerField(default=1)
    body_en = models.TextField()
    body_te = models.TextField(blank=True)
    body_hi = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'safety_waivers'
        unique_together = ('title', 'version')


class ParticipantWaiverAcceptance(UUIDModel):
    participant = models.ForeignKey('bookings.BookingParticipant', on_delete=models.CASCADE, related_name='waivers')
    waiver = models.ForeignKey(SafetyWaiver, on_delete=models.PROTECT, related_name='acceptances')
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'participant_waiver_acceptances'


class EmergencyContact(Timestamped):
    """Organisation-side emergency contacts for a trip (participant emergency contacts live on the participant)."""
    schedule = models.ForeignKey('trips.TripSchedule', null=True, blank=True, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    role = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = 'emergency_contacts'


class IncidentReport(UUIDModel, Timestamped):
    class Severity(models.TextChoices):
        LOW = 'LOW'
        MEDIUM = 'MEDIUM'
        HIGH = 'HIGH'
        CRITICAL = 'CRITICAL'

    schedule = models.ForeignKey('trips.TripSchedule', on_delete=models.PROTECT, related_name='incidents')
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.LOW)
    description = models.TextField()
    occurred_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'incident_reports'
        ordering = ['-occurred_at']


class IncidentAction(TenantBound):
    incident = models.ForeignKey(IncidentReport, on_delete=models.CASCADE, related_name='actions')
    action = models.TextField()
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'incident_actions'


class EmergencyEscalation(TenantBound):
    incident = models.ForeignKey(IncidentReport, on_delete=models.CASCADE, related_name='escalations')
    escalated_to = models.CharField(max_length=150)
    channel = models.CharField(max_length=30, default='phone')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'emergency_escalations'


class TripCompletionReport(UUIDModel, Timestamped):
    schedule = models.OneToOneField('trips.TripSchedule', on_delete=models.CASCADE, related_name='completion_report')
    attended = models.PositiveIntegerField(default=0)
    no_shows = models.PositiveIntegerField(default=0)
    summary = models.TextField(blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'trip_completion_reports'
