"""First-party visitor tracking and BI summaries (sections 9, 10, 13.13, 13.14). PostHog is NOT the source of truth for money/bookings."""
from django.conf import settings
from django.db import models

from core.models import TenantBound, Timestamped, UUIDModel

MONEY = dict(max_digits=14, decimal_places=2)


class Visitor(UUIDModel):
    """Anonymous visitor id (cookie). Contact details are only attached through explicit user actions (9.3)."""
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    first_referrer = models.CharField(max_length=300, blank=True)
    first_landing_path = models.CharField(max_length=300, blank=True)
    do_not_track = models.BooleanField(default=False)

    class Meta:
        db_table = 'visitors'


class TrackingConsent(UUIDModel):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='consents')
    analytics = models.BooleanField(default=False)
    session_replay = models.BooleanField(default=False)
    marketing = models.BooleanField(default=False)
    policy_version = models.CharField(max_length=20, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tracking_consents'
        ordering = ['-created_at']


class VisitorSession(UUIDModel):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    landing_path = models.CharField(max_length=300, blank=True)
    referrer = models.CharField(max_length=300, blank=True)
    utm_source = models.CharField(max_length=80, blank=True)
    utm_medium = models.CharField(max_length=80, blank=True)
    utm_campaign = models.CharField(max_length=120, blank=True, db_index=True)
    channel = models.CharField(max_length=20, blank=True, db_index=True)  # organic | paid | social | referral | direct | email

    class Meta:
        db_table = 'visitor_sessions'


class VisitorEvent(UUIDModel):
    """Append-only event log. `client_event_id` makes duplicate deliveries harmless (test scenario 17)."""
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='events')
    session = models.ForeignKey(VisitorSession, null=True, on_delete=models.SET_NULL, related_name='events')
    client_event_id = models.CharField(max_length=64)
    name = models.CharField(max_length=40, db_index=True)
    path = models.CharField(max_length=300, blank=True)
    properties = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'visitor_events'
        unique_together = ('visitor', 'client_event_id')
        indexes = [models.Index(fields=['name', 'occurred_at'])]


class VisitorDevice(TenantBound):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='devices')
    device_type = models.CharField(max_length=20, blank=True)
    os = models.CharField(max_length=40, blank=True)
    browser = models.CharField(max_length=40, blank=True)
    language = models.CharField(max_length=10, blank=True)

    class Meta:
        db_table = 'visitor_devices'


class VisitorLocation(TenantBound):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='locations')
    city = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=2, blank=True)

    class Meta:
        db_table = 'visitor_locations'


class VisitorInterest(TenantBound):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='interests')
    kind = models.CharField(max_length=20)       # category | destination | trip
    key = models.CharField(max_length=100)
    score = models.FloatField(default=1)

    class Meta:
        db_table = 'visitor_interests'
        unique_together = ('visitor', 'kind', 'key')


class VisitorIdentity(UUIDModel):
    """Link anonymous visitor -> customer, created only on an explicit action (registration, enquiry)."""
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='identities')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='visitor_identities')
    via = models.CharField(max_length=30)        # registration | enquiry | booking
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'visitor_identities'
        unique_together = ('visitor', 'user')


class ConversionEvent(UUIDModel):
    visitor = models.ForeignKey(Visitor, null=True, on_delete=models.SET_NULL, related_name='conversions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=30, db_index=True)   # registration | enquiry | booking | membership
    reference = models.CharField(max_length=64, blank=True)
    value = models.DecimalField(null=True, **MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversion_events'


class VisitorCampaignAttribution(TenantBound):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='attributions')
    campaign = models.ForeignKey('crm.Campaign', null=True, on_delete=models.SET_NULL, related_name='attributions')
    utm_campaign = models.CharField(max_length=120, blank=True)
    touch = models.CharField(max_length=10, default='first')   # first | last
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'visitor_campaign_attributions'


class VisitorRetentionRecord(TenantBound):
    visitor = models.ForeignKey(Visitor, on_delete=models.CASCADE, related_name='retention')
    cohort_week = models.DateField()
    active_week = models.DateField()

    class Meta:
        db_table = 'visitor_retention_records'
        unique_together = ('visitor', 'active_week')


# ---------------- 13.14 Business intelligence ----------------
class AnalyticsEventDefinition(TenantBound):
    name = models.CharField(max_length=40, primary_key=True)
    description = models.CharField(max_length=255, blank=True)
    properties = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'analytics_event_definitions'


class AnalyticsDailySummary(TenantBound):
    day = models.DateField(unique=True)
    visitors = models.PositiveIntegerField(default=0)
    sessions = models.PositiveIntegerField(default=0)
    registrations = models.PositiveIntegerField(default=0)
    bookings = models.PositiveIntegerField(default=0)
    gross_booking_value = models.DecimalField(default=0, **MONEY)
    collections = models.DecimalField(default=0, **MONEY)
    refunds = models.DecimalField(default=0, **MONEY)

    class Meta:
        db_table = 'analytics_daily_summaries'


class MarketingAttributionSummary(TenantBound):
    day = models.DateField()
    channel = models.CharField(max_length=20)
    utm_campaign = models.CharField(max_length=120, blank=True)
    visitors = models.PositiveIntegerField(default=0)
    leads = models.PositiveIntegerField(default=0)
    bookings = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(default=0, **MONEY)
    cost = models.DecimalField(default=0, **MONEY)

    class Meta:
        db_table = 'marketing_attribution_summaries'
        unique_together = ('day', 'channel', 'utm_campaign')


class CustomerMetric(TenantBound):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='metrics')
    bookings = models.PositiveIntegerField(default=0)
    lifetime_value = models.DecimalField(default=0, **MONEY)
    first_booking_at = models.DateTimeField(null=True, blank=True)
    last_booking_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'customer_metrics'


class TripPerformanceSummary(TenantBound):
    schedule = models.OneToOneField('trips.TripSchedule', on_delete=models.CASCADE, related_name='performance')
    bookings = models.PositiveIntegerField(default=0)
    participants = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(default=0, **MONEY)
    expenses = models.DecimalField(default=0, **MONEY)
    profit = models.DecimalField(default=0, **MONEY)
    occupancy_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cancellation_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    refund_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trip_performance_summaries'


class FinancialPerformanceSummary(TenantBound):
    period_start = models.DateField()
    period_end = models.DateField()
    gross_booking_value = models.DecimalField(default=0, **MONEY)
    recognized_revenue = models.DecimalField(default=0, **MONEY)
    collections = models.DecimalField(default=0, **MONEY)
    advance_collected = models.DecimalField(default=0, **MONEY)
    outstanding_balance = models.DecimalField(default=0, **MONEY)
    refunds = models.DecimalField(default=0, **MONEY)
    gateway_fees = models.DecimalField(default=0, **MONEY)
    expenses = models.DecimalField(default=0, **MONEY)
    gst_collected = models.DecimalField(default=0, **MONEY)

    class Meta:
        db_table = 'financial_performance_summaries'
        unique_together = ('period_start', 'period_end')


class OperationalPerformanceSummary(TenantBound):
    day = models.DateField(unique=True)
    pickups_planned = models.PositiveIntegerField(default=0)
    pickups_completed = models.PositiveIntegerField(default=0)
    incidents = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'operational_performance_summaries'


class KpiDefinition(TenantBound):
    """Section 10: every KPI's definition and calculation must be documented."""
    key = models.SlugField(primary_key=True)
    name = models.CharField(max_length=120)
    definition = models.TextField()
    calculation = models.TextField()

    class Meta:
        db_table = 'kpi_definitions'


class ReportDefinition(TenantBound):
    key = models.SlugField(primary_key=True)
    name = models.CharField(max_length=120)
    config = models.JSONField(default=dict)

    class Meta:
        db_table = 'report_definitions'


class ScheduledReport(TenantBound):
    report = models.ForeignKey(ReportDefinition, on_delete=models.CASCADE, related_name='schedules')
    frequency = models.CharField(max_length=10, choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('yearly', 'Yearly')])
    format = models.CharField(max_length=5, choices=[('xlsx', 'Excel'), ('csv', 'CSV'), ('pdf', 'PDF')], default='csv')
    recipients = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'scheduled_reports'


class ReportExecutionHistory(UUIDModel):
    report = models.ForeignKey(ReportDefinition, on_delete=models.CASCADE, related_name='runs')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)
    file = models.FileField(upload_to='reports/%Y/%m/', blank=True)
    status = models.CharField(max_length=10, default='RUNNING')
    error = models.CharField(max_length=300, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'report_execution_history'
