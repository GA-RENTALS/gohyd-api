import uuid

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models


class TenantBound(models.Model):
    tenant = models.ForeignKey(
        'tenancy.Tenant', null=True, blank=True, on_delete=models.PROTECT,
        related_name='%(app_label)s_%(class)s_records',
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from tenancy.context import get_current_tenant
        from tenancy.models import TenantMembership

        current = get_current_tenant()
        if current is None:
            raise ValidationError('Tenant context is required to write tenant-owned data.')
        if self.tenant_id is None:
            self.tenant = current
            update_fields = kwargs.get('update_fields')
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {'tenant'}
        elif self.tenant_id != current.pk:
            raise ValidationError('Tenant-owned data cannot be moved across tenants.')

        for field in self._meta.concrete_fields:
            if not field.is_relation or not field.many_to_one or field.name == 'tenant':
                continue
            related_id = getattr(self, field.attname)
            if related_id is None:
                continue
            related_model = field.remote_field.model
            try:
                related_tenant = related_model._meta.get_field('tenant')
            except FieldDoesNotExist:
                related_tenant = None
            if related_tenant is not None:
                related_tenant_id = related_model._base_manager.filter(
                    pk=related_id,
                ).values_list(related_tenant.attname, flat=True).first()
                if related_tenant_id != current.pk:
                    raise ValidationError(
                        f'{field.name} must reference a record in the active operator.'
                    )
            elif related_model._meta.label_lower == settings.AUTH_USER_MODEL.lower():
                if not related_model._base_manager.filter(pk=related_id, is_superuser=True).exists() and not TenantMembership.objects.filter(
                    tenant=current, user_id=related_id, is_active=True,
                ).exists():
                    raise ValidationError(
                        f'{field.name} must reference a user who belongs to the active operator.'
                    )
        return super().save(*args, **kwargs)


class UUIDModel(TenantBound):
    """Section 14: a consistent primary-key strategy (UUID) for business tables."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class Timestamped(TenantBound):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Language(models.TextChoices):
    EN = 'en', 'English'
    TE = 'te', 'Telugu'
    HI = 'hi', 'Hindi'


class Setting(TenantBound):
    """Admin-editable business settings (advance %, balance due days, business legal details, ...)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=100)
    value = models.JSONField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'settings'
        constraints = [models.UniqueConstraint(fields=('tenant', 'key'), name='unique_tenant_setting_key')]

    def __str__(self):
        return self.key


class AuditLog(UUIDModel):
    """Section 13.16: who did what, to which record, with before/after. Append-only."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=100, db_index=True)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['entity_type', 'entity_id'])]


class DataAccessLog(UUIDModel):
    """Who looked at identifiable personal data (participants, customers)."""
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=64, blank=True)
    purpose = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'data_access_logs'


class SecurityEvent(UUIDModel):
    kind = models.CharField(max_length=60, db_index=True)   # e.g. otp_lockout, webhook_bad_signature
    detail = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'security_events'


class OutboxEvent(UUIDModel):
    """
    Transactional outbox (section 11): written in the same DB transaction as the business change,
    then relayed to Celery by core.tasks.relay_outbox, so payment/booking events can't silently vanish.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING'
        DISPATCHED = 'DISPATCHED'
        FAILED = 'FAILED'

    type = models.CharField(max_length=80, db_index=True)            # e.g. payment.succeeded
    aggregate_id = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'outbox_events'
        ordering = ['created_at']


class DataRequest(UUIDModel):
    """Privacy: export and deletion requests (sections 4.2, 9.3, 13.16)."""
    class Kind(models.TextChoices):
        EXPORT = 'EXPORT'
        DELETION = 'DELETION'

    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED'
        IN_PROGRESS = 'IN_PROGRESS'
        COMPLETED = 'COMPLETED'
        REJECTED = 'REJECTED'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='data_requests')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'data_requests'
