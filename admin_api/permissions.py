from rest_framework.permissions import BasePermission

from tenancy.models import TenantMembership


def has_staff_membership(request):
    user = request.user
    if not user or not user.is_authenticated or not user.is_staff:
        return False
    if user.is_superuser:
        return True
    tenant = getattr(request, 'tenant', None)
    return bool(tenant and TenantMembership.objects.filter(
        tenant=tenant,
        user=user,
        is_active=True,
        role__in=(TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN),
    ).exists())


class StaffModelPermission(BasePermission):
    """Require an authenticated staff account and the Django permission for this model/action."""

    def has_permission(self, request, view):
        user = request.user
        if not has_staff_membership(request):
            return False
        resource = view.get_resource()
        action = getattr(view, 'action', None)
        method = request.method.upper()
        if action in {'list', 'retrieve', 'schema'} or method in {'GET', 'HEAD', 'OPTIONS'}:
            codename = 'view'
        elif action == 'create' or method == 'POST':
            codename = 'add'
        elif action in {'update', 'partial_update'} or method in {'PUT', 'PATCH'}:
            codename = 'change'
        elif action == 'destroy' or method == 'DELETE':
            codename = 'delete'
        else:
            return False
        return user.has_perm(f'{resource.model._meta.app_label}.{codename}_{resource.model._meta.model_name}')


class StaffOnly(BasePermission):
    def has_permission(self, request, view):
        return has_staff_membership(request)
