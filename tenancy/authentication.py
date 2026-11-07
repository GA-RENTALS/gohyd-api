from rest_framework.exceptions import AuthenticationFailed
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import TenantMembership


def _bind_tenant_membership(request, user, token_tenant_id=None, require_token_tenant=False):
    django_request = getattr(request, '_request', request)
    tenant = getattr(django_request, 'tenant', None)
    if tenant is None:
        raise AuthenticationFailed('A verified operator domain is required.')
    if require_token_tenant and str(token_tenant_id or '') != str(tenant.pk):
        raise AuthenticationFailed('The token is not valid for this operator.')

    membership = TenantMembership.objects.filter(
        tenant=tenant, user=user, is_active=True,
    ).first()
    if membership is None and not user.is_superuser:
        raise AuthenticationFailed('Active membership in this operator is required.')

    django_request.tenant_membership = membership


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, validated_token = result
        _bind_tenant_membership(
            request, user, validated_token.get('tenant_id'), require_token_tenant=True,
        )
        return user, validated_token


class TenantSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, auth = result
        _bind_tenant_membership(request, user)
        return user, auth
