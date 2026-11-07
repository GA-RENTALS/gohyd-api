from django.contrib import admin

from .models import Tenant, TenantDomain, TenantMembership


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    readonly_fields = ('id', 'created_at')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TenantDomain)
class TenantDomainAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'tenant', 'is_verified')
    list_filter = ('is_verified',)
    search_fields = ('hostname', 'tenant__name')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant', 'role', 'is_active')
    list_filter = ('tenant', 'role', 'is_active')
    search_fields = ('user__phone_number', 'user__email', 'tenant__name')
    readonly_fields = ('created_at',)

    def _is_tenant_admin(self, request):
        if request.user.is_superuser:
            return True
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and TenantMembership.objects.filter(
            tenant=tenant,
            user=request.user,
            role=TenantMembership.Role.TENANT_ADMIN,
            is_active=True,
        ).exists())

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(tenant=getattr(request, 'tenant', None))

    def has_add_permission(self, request):
        return self._is_tenant_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_tenant_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_tenant_admin(request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and 'tenant' in form.base_fields:
            form.base_fields.pop('tenant')
        return form

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.tenant = request.tenant
        super().save_model(request, obj, form, change)
