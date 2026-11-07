from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AuditLog, DataAccessLog, DataRequest, OutboxEvent, SecurityEvent, Setting


class ReadOnlyAdmin(ModelAdmin):
    """Audit-style tables: viewable, never editable or deletable from the admin."""
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'actor', 'action', 'entity_type', 'entity_id', 'ip')
    list_filter = ('action', 'entity_type')
    search_fields = ('entity_id', 'actor__phone_number', 'action')
    date_hierarchy = 'created_at'


@admin.register(DataAccessLog)
class DataAccessLogAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'actor', 'entity_type', 'entity_id', 'purpose')


@admin.register(SecurityEvent)
class SecurityEventAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'kind', 'ip')
    list_filter = ('kind',)


@admin.register(OutboxEvent)
class OutboxEventAdmin(ReadOnlyAdmin):
    list_display = ('created_at', 'type', 'aggregate_id', 'status', 'attempts', 'last_error')
    list_filter = ('status', 'type')


@admin.register(Setting)
class SettingAdmin(ModelAdmin):
    list_display = ('key', 'value', 'description', 'updated_at')
    search_fields = ('key',)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(DataRequest)
class DataRequestAdmin(ModelAdmin):
    list_display = ('created_at', 'user', 'kind', 'status')
    list_filter = ('kind', 'status')


def register_remaining(app_label, skip=(), readonly=()):
    """Register every model of an app that has no explicit admin yet (Unfold-styled). Readonly ones are view-only."""
    from django.apps import apps
    for model in apps.get_app_config(app_label).get_models():
        if model in admin.site._registry or model.__name__ in skip or model._meta.auto_created or 'Historical' in model.__name__:
            continue
        base = ReadOnlyAdmin if model.__name__ in readonly else ModelAdmin
        admin.site.register(model, type(f'{model.__name__}Admin', (base,), {}))
