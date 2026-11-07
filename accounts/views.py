import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from django.core.cache import cache
from django.contrib.auth.hashers import check_password, make_password

from . import otp
from .models import CustomerProfile, LoginHistory, User
from .serializers import (
    LogoutSerializer, PasswordLoginSerializer, ProfileSerializer, RequestOTPSerializer,
    TenantTokenRefreshSerializer, VerifyOTPSerializer,
)
from .services import WhatsAppService
from .tasks import send_whatsapp_otp_task
from tenancy.models import TenantMembership
from core.security import get_client_ip
from core.throttling import TrustedScopedRateThrottle

logger = logging.getLogger(__name__)


def client_ip(request):
    return get_client_ip(request)


def tokens_for(user, tenant):
    membership = TenantMembership.objects.filter(
        tenant=tenant, user=user, is_active=True,
    ).first()
    if membership is None and not user.is_superuser:
        raise PermissionDenied('Active membership in this operator is required.')
    r = RefreshToken.for_user(user)
    r['tenant_id'] = str(tenant.pk)
    return {'access': str(r.access_token), 'refresh': str(r)}


def error(message, code, retry_after=None):
    resp = Response({'status': 'error', 'message': message}, status=code)
    if retry_after:
        resp['Retry-After'] = str(retry_after)
    return resp


class RequestOTPView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'otp_request'

    @extend_schema(tags=['Auth'], summary='Send a sign-in code by WhatsApp', request=RequestOTPSerializer)
    def post(self, request):
        s = RequestOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone = s.validated_data['phone_number']
        try:
            rec, code = otp.request_otp(phone, client_ip(request))
        except otp.OtpError as e:
            return error(e.message, e.status, e.retry_after)
        if settings.OTP_LOG_IN_CONSOLE:
            logger.warning('Development sign-in code for %s: %s', phone, code)
        elif settings.OTP_SEND_INLINE:
            # development: no worker needed; if Meta refuses (template not approved, sandbox number…) the code still appears in the console
            try:
                WhatsAppService.send_otp(phone, code)
            except Exception as exc:   # noqa: BLE001
                logger.warning('WhatsApp send failed (%s). Development sign-in code for %s: %s', type(exc).__name__, phone, code)
        else:
            try:
                send_whatsapp_otp_task.delay(phone, code)
            except Exception:
                logger.exception("Couldn't queue a sign-in code")
                rec.invalidated_at = rec.created_at; rec.save(update_fields=['invalidated_at'])
                return error("We couldn't send your code just now. Please try again.", 503)
        # same response whether or not the number has an account (no enumeration)
        return Response({'status': 'success', 'message': 'Code sent via WhatsApp.',
                         'expires_in_seconds': settings.OTP_TTL_SECONDS, 'resend_in_seconds': settings.OTP_RESEND_SECONDS})


class VerifyOTPView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'otp_verify'

    @extend_schema(tags=['Auth'], summary='Check a code and get login tokens', request=VerifyOTPSerializer)
    def post(self, request):
        s = VerifyOTPSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user, created = otp.verify_otp(s.validated_data['phone_number'], s.validated_data['otp'],
                                           client_ip(request), request.META.get('HTTP_USER_AGENT', ''))
        except otp.OtpError as e:
            return error(e.message, e.status)
        tenant = request.tenant
        membership = TenantMembership.objects.filter(tenant=tenant, user=user).first()
        if membership is None and user.kind == user.Kind.CUSTOMER and not user.is_superuser:
            membership = TenantMembership.objects.create(
                tenant=tenant, user=user, role=TenantMembership.Role.CUSTOMER,
            )
        elif membership is None and user.is_superuser:
            membership = TenantMembership.objects.create(
                tenant=tenant, user=user, role=TenantMembership.Role.TENANT_ADMIN,
            )
        elif membership is None:
            return error('An operator administrator must be provisioned by an administrator.', 403)
        if not membership.is_active:
            return error('Active membership in this operator is required.', 403)
        CustomerProfile.objects.get_or_create(user=user, tenant=tenant)
        return Response({'status': 'success', 'is_new_user': created, 'is_profile_complete': user.is_profile_complete, **tokens_for(user, tenant)})


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Account'], responses=ProfileSerializer)
    def get(self, request):
        return Response(ProfileSerializer(request.user, context={'request': request}).data)

    @extend_schema(tags=['Account'], request=ProfileSerializer, responses=ProfileSerializer)
    def patch(self, request):
        s = ProfileSerializer(request.user, data=request.data, partial=True, context={'request': request})
        s.is_valid(raise_exception=True)
        user = s.save()
        if user.full_name and not user.is_profile_complete:
            user.is_profile_complete = True
            user.save(update_fields=['is_profile_complete'])
        return Response(ProfileSerializer(user, context={'request': request}).data)


class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=['Auth'], request=LogoutSerializer, responses={204: None})
    def post(self, request):
        s = LogoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            RefreshToken(s.validated_data['refresh']).blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantTokenRefreshView(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = TenantTokenRefreshSerializer

    @extend_schema(tags=['Auth'], summary='Refresh a token for the current operator')
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


# A fixed hash so a wrong phone number costs the same time as a wrong password (no account probing by timing).
_DUMMY_HASH = make_password('not-a-real-password')
PASSWORD_MAX_FAILURES = 5
PASSWORD_LOCK_SECONDS = 15 * 60


class PasswordLoginView(APIView):
    """Staff sign-in with phone number + password (customers keep using the WhatsApp code)."""
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'password_login'

    @extend_schema(tags=['Auth'], summary='Staff sign-in with a password', request=PasswordLoginSerializer)
    def post(self, request):
        s = PasswordLoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        phone, password = s.validated_data['phone_number'], s.validated_data['password']
        ip = client_ip(request)
        generic = 'Invalid phone number or password.'
        lock_key = f'pwlock:{phone}'
        if cache.get(lock_key, 0) >= PASSWORD_MAX_FAILURES:
            return error('Too many failed attempts. Try again in 15 minutes, or sign in with a code.', 429, PASSWORD_LOCK_SECONDS)

        user = User.objects.filter(phone_number=phone).first()
        ok = check_password(password, user.password if user else _DUMMY_HASH) and user is not None
        tenant = request.tenant
        membership = TenantMembership.objects.filter(
            tenant=tenant, user=user, is_active=True,
            role__in=(TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN),
        ).first() if ok else None
        allowed = ok and user.is_active and not user.deleted_at and user.is_staff and (membership is not None or user.is_superuser)
        if not allowed:
            cache.set(lock_key, cache.get(lock_key, 0) + 1, PASSWORD_LOCK_SECONDS)
            LoginHistory.objects.create(phone_number=phone, success=False, reason='bad_password', ip=ip, user_agent=request.META.get('HTTP_USER_AGENT', '')[:300])
            return error(generic, 400)
        cache.delete(lock_key)
        LoginHistory.objects.create(user=user, phone_number=phone, success=True, ip=ip, user_agent=request.META.get('HTTP_USER_AGENT', '')[:300])
        return Response({'status': 'success', **tokens_for(user, tenant)})
