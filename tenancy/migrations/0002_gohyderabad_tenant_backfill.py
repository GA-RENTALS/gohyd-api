from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import migrations


def create_initial_tenant_and_backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Tenant = apps.get_model('tenancy', 'Tenant')
    TenantDomain = apps.get_model('tenancy', 'TenantDomain')
    TenantMembership = apps.get_model('tenancy', 'TenantMembership')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    tenant, _ = Tenant.objects.using(alias).get_or_create(
        slug='gohyderabad',
        defaults={'name': 'GoHyderabad'},
    )
    for hostname in ('localhost', '127.0.0.1', '::1', 'testserver'):
        TenantDomain.objects.using(alias).get_or_create(
            hostname=hostname,
            defaults={'tenant_id': tenant.pk, 'is_verified': True},
        )

    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        try:
            model._meta.get_field('tenant')
        except FieldDoesNotExist:
            continue
        model._base_manager.using(alias).filter(tenant__isnull=True).update(tenant_id=tenant.pk)

    for user in User._base_manager.using(alias).all().iterator():
        if user.is_superuser or user.is_staff:
            role = 'TENANT_ADMIN'
        else:
            role = 'CUSTOMER'
        TenantMembership.objects.using(alias).get_or_create(
            tenant_id=tenant.pk,
            user_id=user.pk,
            defaults={
                'role': role,
                'is_active': user.is_active and not getattr(user, 'deleted_at', None),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_alter_team_name_and_more'),
        ('bookings', '0003_booking_tenant_bookingcancellation_tenant_and_more'),
        ('content', '0004_blog_tenant_blogcategory_tenant_blogtag_tenant_and_more'),
        ('core', '0003_setting_tenant_key'),
        ('crm', '0003_campaign_tenant_campaignchannel_tenant_and_more'),
        ('notifications', '0002_backupexecutionlog_tenant_and_more'),
        ('operations', '0003_driver_tenant_emergencycontact_tenant_and_more'),
        ('payments', '0003_businessentity_tenant_creditnote_tenant_and_more'),
        ('tenancy', '0001_initial'),
        ('tracking', '0002_analyticsdailysummary_tenant_and_more'),
        ('trips', '0002_event_tenant_eventattendance_tenant_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(create_initial_tenant_and_backfill, migrations.RunPython.noop),
    ]
