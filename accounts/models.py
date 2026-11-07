import re

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, Group, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import Language, TenantBound, Timestamped, UUIDModel

PHONE_RE = re.compile(r'^\+91[6-9]\d{9}$')


def normalize_phone(raw: str) -> str:
    """'98765 43210', '+91-9876543210', '09876543210' -> '+919876543210'. Raises ValidationError otherwise."""
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]
    phone = f'+91{digits}'
    if len(digits) != 10 or not PHONE_RE.match(phone):
        raise ValidationError('Enter a valid 10-digit Indian mobile number.')
    return phone


class UserManager(BaseUserManager):
    def create_user(self, phone_number, password=None, **extra):
        if not phone_number:
            raise ValueError('Phone number must be provided.')
        extra.setdefault('is_active', True)
        user = self.model(phone_number=phone_number, **extra)
        user.set_password(password) if password else user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone_number, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, is_profile_complete=True, kind=User.Kind.ADMIN)
        if not password:
            raise ValueError('Superuser must have a password.')
        return self.create_user(phone_number, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """One table for customers and staff. Only the primary booker has a customer account (section 3.4)."""
    class Kind(models.TextChoices):
        CUSTOMER = 'CUSTOMER'
        ADMIN = 'ADMIN'

    phone_number = models.CharField(max_length=20, unique=True, db_index=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUSTOMER)
    full_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True, null=True, unique=True)
    preferred_language = models.CharField(max_length=2, choices=Language.choices, default=Language.EN)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_profile_complete = models.BooleanField(default=False)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True, help_text='Soft delete for privacy requests; rows kept for financial records.')

    objects = UserManager()
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.full_name or self.phone_number


class CustomerProfile(Timestamped):
    """Billing and notification preferences (sections 3.5, 4.2)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='customer_profiles')
    billing_name = models.CharField(max_length=200, blank=True)
    billing_gstin = models.CharField(max_length=15, blank=True)
    billing_address = models.TextField(blank=True)
    notify_whatsapp = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=True)
    notify_sms = models.BooleanField(default=False)
    marketing_opt_in = models.BooleanField(default=False)

    class Meta:
        db_table = 'customer_profiles'
        constraints = [models.UniqueConstraint(fields=('tenant', 'user'), name='unique_tenant_customer_profile')]


class AdminProfile(Timestamped):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_profiles')
    designation = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'admin_profiles'
        constraints = [models.UniqueConstraint(fields=('tenant', 'user'), name='unique_tenant_admin_profile')]


class Team(Timestamped):
    """Team-based permissions: a team carries Django groups; members inherit them."""
    name = models.CharField(max_length=100)
    groups = models.ManyToManyField(Group, blank=True, related_name='teams')
    members = models.ManyToManyField(User, blank=True, related_name='teams')

    class Meta:
        db_table = 'teams'
        constraints = [models.UniqueConstraint(fields=('tenant', 'name'), name='unique_tenant_team_name')]

    def __str__(self):
        return self.name


class ResourceAssignment(UUIDModel):
    """Resource-specific access: this user may act on this particular trip/destination/etc."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resource_assignments')
    resource_type = models.CharField(max_length=50)   # 'trip', 'destination', 'event'
    resource_id = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'resource_assignments'
        unique_together = ('tenant', 'user', 'resource_type', 'resource_id')


class LoginHistory(UUIDModel):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='login_history')
    phone_number = models.CharField(max_length=20, db_index=True)
    success = models.BooleanField()
    reason = models.CharField(max_length=60, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'login_history'
        ordering = ['-created_at']


class OtpVerificationRecord(UUIDModel):
    """The OTP itself is never stored: only an HMAC of it (section 4.1)."""
    phone_number = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=64)
    channel = models.CharField(max_length=10, default='WHATSAPP')   # or SMS (fallback)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'otp_verification_records'
        indexes = [models.Index(fields=['phone_number', 'created_at'])]
