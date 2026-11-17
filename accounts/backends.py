"""Authentication permissions scoped to the active operator membership."""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import Permission

from tenancy.context import get_current_tenant
from tenancy.models import TenantMembership
from tenancy.roles import STAFF_ROLE_NAMES


class TenantRoleBackend(ModelBackend):
    """Use the role stored on this tenant's membership, never global user groups."""

    def get_group_permissions(self, user_obj, obj=None):
        if obj is not None or not user_obj.is_active or user_obj.is_anonymous:
            return set()
        tenant = get_current_tenant()
        if tenant is None:
            return set()

        cache = getattr(user_obj, '_tenant_role_permissions', {})
        tenant_key = str(tenant.pk)
        if tenant_key in cache:
            return cache[tenant_key]

        membership = TenantMembership.objects.filter(
            tenant=tenant,
            user=user_obj,
            is_active=True,
            role__in=(TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN),
        ).first()
        if membership is None:
            permissions = set()
        else:
            role_name = membership.staff_role
            if not role_name:
                # Compatibility for a legacy single-operator account before its membership is migrated.
                # Never infer a role from global groups once the user has staff access to multiple tenants.
                staff_memberships = TenantMembership.objects.filter(
                    user=user_obj,
                    is_active=True,
                    role__in=(TenantMembership.Role.STAFF, TenantMembership.Role.TENANT_ADMIN),
                ).count()
                if staff_memberships == 1:
                    role_name = user_obj.groups.filter(name__in=STAFF_ROLE_NAMES).order_by('name').values_list('name', flat=True).first() or ''
            permissions = {
                f'{app_label}.{codename}'
                for app_label, codename in Permission.objects.filter(group__name=role_name).values_list(
                    'content_type__app_label', 'codename',
                )
            } if role_name else set()

        cache[tenant_key] = permissions
        user_obj._tenant_role_permissions = cache
        return permissions

    def get_user_permissions(self, user_obj, obj=None):
        # Direct Django user permissions have no tenant boundary. Staff access is granted through
        # the membership's role group; platform superusers are handled by PermissionsMixin.
        return set()

    def get_all_permissions(self, user_obj, obj=None):
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        if user_obj.is_superuser:
            # has_perm() already allows a superuser everything; the admin UI reads this list to show controls.
            return {f'{app}.{codename}' for app, codename in
                    Permission.objects.values_list('content_type__app_label', 'codename')}
        return self.get_group_permissions(user_obj)
