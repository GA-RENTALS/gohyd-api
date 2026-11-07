from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin, StackedInline

from core.admin import ReadOnlyAdmin
from tenancy.models import TenantMembership

from .models import AdminProfile, CustomerProfile, LoginHistory, OtpVerificationRecord, ResourceAssignment, Team, User

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    search_fields = ('name',)
    filter_horizontal = ('permissions',)

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


class CustomerProfileInline(StackedInline):
    model = CustomerProfile
    extra = 0


class AdminProfileInline(StackedInline):
    model = AdminProfile
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    ordering = ('-date_joined',)
    list_display = ('phone_number', 'full_name', 'kind', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('kind', 'is_staff', 'is_active', 'groups')
    search_fields = ('phone_number', 'full_name', 'email')
    inlines = [CustomerProfileInline, AdminProfileInline]
    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('Profile', {'fields': ('full_name', 'email', 'preferred_language', 'kind', 'is_profile_complete', 'phone_verified_at')}),
        ('Access', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Privacy', {'fields': ('deleted_at',)}),
    )
    add_fieldsets = ((None, {'classes': ('wide',), 'fields': ('phone_number', 'kind', 'password1', 'password2')}),)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return qs.none()
        return qs.filter(
            tenant_memberships__tenant=tenant,
            tenant_memberships__is_active=True,
        ).distinct()

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_fieldsets(request, obj)
        if obj is None:
            return ((None, {'fields': ('phone_number',)}),)
        return (
            (None, {'fields': ('phone_number',)}),
            ('Profile', {'fields': ('full_name', 'email', 'preferred_language')}),
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            return tuple(readonly) + ('phone_number',)
        return readonly

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name in {'groups', 'user_permissions'} and not request.user.is_superuser:
            kwargs['queryset'] = db_field.remote_field.model.objects.none()
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Team)
class TeamAdmin(ModelAdmin):
    list_display = ('name',)
    filter_horizontal = ('groups', 'members')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(tenant=getattr(request, 'tenant', None))

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser and 'groups' in form.base_fields:
            form.base_fields.pop('groups')
        return form

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == 'members' and not request.user.is_superuser:
            tenant = getattr(request, 'tenant', None)
            kwargs['queryset'] = db_field.remote_field.model.objects.filter(
                tenant_memberships__tenant=tenant,
                tenant_memberships__is_active=True,
            )
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(ResourceAssignment)
class ResourceAssignmentAdmin(ModelAdmin):
    list_display = ('user', 'resource_type', 'resource_id')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(tenant=getattr(request, 'tenant', None))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user' and not request.user.is_superuser:
            kwargs['queryset'] = db_field.remote_field.model.objects.filter(
                tenant_memberships__tenant=getattr(request, 'tenant', None),
                tenant_memberships__is_active=True,
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(LoginHistory)
class LoginHistoryAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'phone_number', 'success', 'reason', 'ip')
    list_filter = ('success', 'reason')


@admin.register(OtpVerificationRecord)
class OtpAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'phone_number', 'attempts', 'expires_at', 'consumed_at')
    exclude = ('code_hash',)
