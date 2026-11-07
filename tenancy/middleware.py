from urllib.parse import urlsplit

from django.db import connection, transaction
from django.http import HttpResponse

from .context import reset_current_tenant, set_current_tenant
from .models import TenantDomain


class TenantContextMiddleware:
    """Resolve the tenant from a verified request hostname and scope the whole request transaction."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        hostname = (urlsplit(f'//{request.get_host()}').hostname or '').rstrip('.').lower()
        with transaction.atomic():
            domain = (TenantDomain.objects.select_related('tenant')
                      .filter(hostname=hostname, is_verified=True, tenant__is_active=True).first())
            tenant = domain.tenant if domain else None
            request.tenant = tenant
            token = set_current_tenant(tenant)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('app.tenant_id', %s, true)",
                        [str(tenant.pk) if tenant else ''],
                    )

                if (request.path.startswith(('/api/v1/', '/webhooks/'))
                        and tenant is None):
                    return HttpResponse(status=404)

                if request.path.startswith('/admin/') and getattr(request.user, 'is_authenticated', False):
                    if not request.user.is_superuser:
                        if request.path.startswith(('/admin/auth/group/', '/admin/token_blacklist/')):
                            return HttpResponse(status=403)
                        from .models import TenantMembership
                        membership = TenantMembership.objects.filter(
                            tenant=tenant,
                            user=request.user,
                            is_active=True,
                            role__in=(TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN),
                        ).first() if tenant else None
                        if membership is None or not request.user.is_staff:
                            return HttpResponse(status=403)
                if (tenant is not None and request.path.startswith('/admin/')
                        and getattr(request.user, 'is_authenticated', False)
                        and getattr(request.user, 'is_superuser', False)):
                    from core.models import SecurityEvent
                    SecurityEvent.objects.create(
                        kind='platform_admin_tenant_access',
                        detail={'path': request.path[:200], 'tenant_id': str(tenant.pk)},
                    )

                return self.get_response(request)
            finally:
                reset_current_tenant(token)
