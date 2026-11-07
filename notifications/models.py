"""Notifications and integrations (sections 12, 13.15). Templates exist in English, Telugu and Hindi."""
from django.conf import settings
from django.db import models

from core.models import Language, TenantBound, Timestamped, UUIDModel


class NotificationEvent(models.TextChoices):
    OTP = 'otp'
    REGISTRATION = 'registration'
    BOOKING_CONFIRMATION = 'booking_confirmation'
    ADVANCE_PAYMENT = 'advance_payment'
    BALANCE_REMINDER = 'balance_reminder'
    PAYMENT_RECEIPT = 'payment_receipt'
    INVOICE = 'invoice'
    PICKUP_CHANGE = 'pickup_change'
    TRIP_REMINDER = 'trip_reminder'
    CANCELLATION = 'cancellation'
    REFUND = 'refund'
    MEMBERSHIP = 'membership'
    ENQUIRY_RESPONSE = 'enquiry_response'


class Channel(models.TextChoices):
    WHATSAPP = 'whatsapp'
    EMAIL = 'email'
    SMS = 'sms'
    IN_APP = 'in_app'


class NotificationTemplate(Timestamped):
    event = models.CharField(max_length=30, choices=NotificationEvent.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    provider_template_name = models.CharField(max_length=100, blank=True, help_text='Approved WhatsApp/SMS template id.')
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_templates'
        unique_together = ('event', 'channel')

    def missing_languages(self):
        have = set(self.translations.exclude(body='').values_list('language', flat=True))
        return [l for l, _ in Language.choices if l not in have]

    def __str__(self):
        return f'{self.event}/{self.channel}'


class NotificationTranslation(TenantBound):
    template = models.ForeignKey(NotificationTemplate, on_delete=models.CASCADE, related_name='translations')
    language = models.CharField(max_length=2, choices=Language.choices)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField(help_text='Use {name}, {reference}, {amount}, {due_date}, {trip} placeholders.')

    class Meta:
        db_table = 'notification_translations'
        unique_together = ('template', 'language')


class NotificationPreference(TenantBound):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')
    event = models.CharField(max_length=30, choices=NotificationEvent.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    enabled = models.BooleanField(default=True)

    class Meta:
        db_table = 'notification_preferences'
        unique_together = ('user', 'event', 'channel')


class NotificationJob(UUIDModel, Timestamped):
    class Status(models.TextChoices):
        QUEUED = 'QUEUED'
        SENT = 'SENT'
        FAILED = 'FAILED'
        SKIPPED = 'SKIPPED'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='notifications')
    event = models.CharField(max_length=30, choices=NotificationEvent.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    language = models.CharField(max_length=2, choices=Language.choices, default='en')
    context = models.JSONField(default=dict)
    dedupe_key = models.CharField(max_length=120, unique=True, help_text='Same key = same message; prevents duplicates on retries.')
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.QUEUED, db_index=True)
    is_read = models.BooleanField(default=False, help_text='For in-app notifications.')
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'notification_jobs'
        ordering = ['-created_at']


class NotificationDeliveryLog(TenantBound):
    job = models.ForeignKey(NotificationJob, on_delete=models.CASCADE, related_name='deliveries')
    provider_message_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification_delivery_logs'


class NotificationFailure(TenantBound):
    job = models.ForeignKey(NotificationJob, on_delete=models.CASCADE, related_name='failures')
    error = models.CharField(max_length=500)
    attempt = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification_failures'


class IntegrationProvider(TenantBound):
    key = models.SlugField(primary_key=True)      # razorpay, whatsapp, posthog, s3, sms
    name = models.CharField(max_length=80)

    class Meta:
        db_table = 'integration_providers'

    def __str__(self):
        return self.name


class IntegrationConfiguration(Timestamped):
    provider = models.OneToOneField(IntegrationProvider, on_delete=models.CASCADE, related_name='configuration')
    enabled = models.BooleanField(default=False)
    public_config = models.JSONField(default=dict, blank=True, help_text='Non-secret settings only. Secrets live in env / AWS Secrets Manager.')

    class Meta:
        db_table = 'integration_configurations'


class WebhookRecord(UUIDModel):
    provider = models.ForeignKey(IntegrationProvider, on_delete=models.CASCADE, related_name='webhooks')
    event_id = models.CharField(max_length=100, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_records'


class WebhookLog(TenantBound):
    record = models.ForeignKey(WebhookRecord, on_delete=models.CASCADE, related_name='logs')
    message = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_logs'


class IntegrationExecutionLog(TenantBound):
    provider = models.ForeignKey(IntegrationProvider, on_delete=models.CASCADE, related_name='executions')
    operation = models.CharField(max_length=80)
    success = models.BooleanField()
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'integration_execution_logs'


class IntegrationHealthStatus(TenantBound):
    provider = models.OneToOneField(IntegrationProvider, on_delete=models.CASCADE, related_name='health')
    healthy = models.BooleanField(default=True)
    checked_at = models.DateTimeField(auto_now=True)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'integration_health_status'


class BackupExecutionLog(TenantBound):
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    success = models.BooleanField(default=False)
    restore_tested = models.BooleanField(default=False)
    detail = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'backup_execution_logs'


class SystemHealthLog(TenantBound):
    component = models.CharField(max_length=40)
    healthy = models.BooleanField()
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'system_health_logs'
