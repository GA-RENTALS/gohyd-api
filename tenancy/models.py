import ipaddress
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'tenants'
        ordering = ['name']

    def __str__(self):
        return self.name


class TenantDomain(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='domains')
    hostname = models.CharField(max_length=253, unique=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'tenant_domains'
        ordering = ['hostname']

    def clean(self):
        try:
            host = self.hostname.strip().rstrip('.').encode('idna').decode('ascii').lower()
        except UnicodeError as exc:
            raise ValidationError({'hostname': 'Enter a valid hostname.'}) from exc
        if not host or len(host) > 253 or any(char in host for char in '/@'):
            raise ValidationError({'hostname': 'Enter a hostname without a scheme, port, or path.'})
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if ':' in host:
                raise ValidationError({'hostname': 'Enter a valid hostname.'})
            labels = host.split('.')
            if any(
                not label or len(label) > 63
                or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label)
                for label in labels
            ):
                raise ValidationError({'hostname': 'Enter a valid hostname.'})
        self.hostname = host

    def save(self, *args, **kwargs):
        self.hostname = self.hostname.strip().rstrip('.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.hostname


class TenantMembership(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Customer'
        STAFF = 'STAFF', 'Staff'
        TENANT_ADMIN = 'TENANT_ADMIN', 'Tenant admin'

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tenant_memberships')
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = 'tenant_memberships'
        constraints = [
            models.UniqueConstraint(fields=('tenant', 'user'), name='unique_tenant_user_membership'),
        ]
        indexes = [models.Index(fields=('tenant', 'role', 'is_active'))]

    def __str__(self):
        return f'{self.user} · {self.tenant} · {self.role}'
