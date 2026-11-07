"""WhatsApp OTP (section 4.1): secure generation, hashing, expiry, attempt limits, resend throttling, rate limits."""
import hashlib
import hmac
import secrets

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from datetime import timedelta

from core.models import SecurityEvent
from core.services import audit

from .models import LoginHistory, OtpVerificationRecord, User


class OtpError(Exception):
    def __init__(self, message, status=400, retry_after=None):
        super().__init__(message)
        self.message, self.status, self.retry_after = message, status, retry_after


def _hash(phone, code):
    return hmac.new(settings.SECRET_KEY.encode(), f'otp:{phone}:{code}'.encode(), hashlib.sha256).hexdigest()


def _hit(key, limit, window, message):
    cache.add(key, 0, timeout=window)
    if cache.incr(key) > limit:
        raise OtpError(message, 429, retry_after=window)


def request_otp(phone, ip):
    _hit(f'otp:ip:{ip}', int(getattr(settings, 'OTP_IP_HOURLY_LIMIT', 20)), 3600, 'Too many requests. Try again later.')
    _hit(f'otp:phone:{phone}', int(getattr(settings, 'OTP_PHONE_HOURLY_LIMIT', 5)), 3600, 'Too many codes requested for this number.')
    if not cache.add(f'otp:cooldown:{phone}', 1, timeout=settings.OTP_RESEND_SECONDS):
        raise OtpError(f'Wait {settings.OTP_RESEND_SECONDS} seconds before asking for another code.', 429, settings.OTP_RESEND_SECONDS)

    code = f'{secrets.randbelow(1_000_000):06d}'
    with transaction.atomic():
        OtpVerificationRecord.objects.filter(phone_number=phone, consumed_at__isnull=True, invalidated_at__isnull=True) \
            .update(invalidated_at=timezone.now())
        rec = OtpVerificationRecord.objects.create(
            phone_number=phone, code_hash=_hash(phone, code), max_attempts=settings.OTP_MAX_ATTEMPTS, ip=ip,
            expires_at=timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS))
    return rec, code


def verify_otp(phone, code, ip, user_agent=''):
    """
    Failed attempts must be COMMITTED (otherwise the attempt limit is bypassed by the rollback an exception causes),
    so the transaction returns an outcome and errors are raised only after it has committed.
    """
    outcome, user, created = 'no_code', None, False
    with transaction.atomic():
        rec = (OtpVerificationRecord.objects.select_for_update()
               .filter(phone_number=phone, consumed_at__isnull=True, invalidated_at__isnull=True, expires_at__gt=timezone.now())
               .order_by('-created_at').first())
        if rec:
            if rec.attempts >= rec.max_attempts:
                rec.invalidated_at = timezone.now(); rec.save(update_fields=['invalidated_at'])
                outcome = 'attempts_exhausted'
            else:
                rec.attempts += 1
                if not hmac.compare_digest(rec.code_hash, _hash(phone, code)):
                    if rec.attempts >= rec.max_attempts:
                        rec.invalidated_at = timezone.now()
                    rec.save(update_fields=['attempts', 'invalidated_at'])
                    outcome = 'wrong_code'
                else:
                    existing = User.objects.filter(phone_number=phone).first()
                    if existing and (not existing.is_active or existing.deleted_at):
                        rec.save(update_fields=['attempts'])
                        outcome = 'account_disabled'
                    else:
                        rec.consumed_at = timezone.now()
                        rec.save(update_fields=['attempts', 'consumed_at'])
                        user, created = User.objects.get_or_create(phone_number=phone)
                        if not user.phone_verified_at:
                            user.phone_verified_at = timezone.now(); user.save(update_fields=['phone_verified_at'])
                        outcome = 'ok'
    if outcome == 'ok':
        # A first-time customer must belong to the operator before tenant-bound rows (login history, audit) can reference them.
        from tenancy.context import get_current_tenant
        from tenancy.models import TenantMembership
        tenant = get_current_tenant()
        if tenant is not None and user.kind == user.Kind.CUSTOMER and not user.is_superuser:
            TenantMembership.objects.get_or_create(tenant=tenant, user=user, defaults={'role': TenantMembership.Role.CUSTOMER})
        LoginHistory.objects.create(user=user, phone_number=phone, success=True, ip=ip, user_agent=user_agent[:300])
        audit(user, 'auth.login', 'User', user.pk)
        return user, created
    LoginHistory.objects.create(phone_number=phone, success=False, reason=outcome, ip=ip, user_agent=user_agent[:300])
    if outcome == 'attempts_exhausted' or (outcome == 'wrong_code' and rec and rec.invalidated_at):
        SecurityEvent.objects.create(kind='otp_lockout', detail={'phone': phone}, ip=ip)
    messages = {
        'no_code': ('Invalid or expired code. Request a new one.', 400),
        'wrong_code': ('Incorrect code.' if not (rec and rec.invalidated_at) else 'Too many wrong codes. Ask for a new one.', 400),
        'attempts_exhausted': ('Too many wrong codes. Ask for a new one.', 400),
        'account_disabled': ('This account is disabled.', 403),
    }
    msg, status = messages[outcome]
    raise OtpError(msg, status)
