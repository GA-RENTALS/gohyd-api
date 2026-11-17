from django.db import migrations, models


LEGACY_STAFF_ROLES = (
    'Super Admin', 'Admin', 'Content Manager', 'Content Writer', 'Trip Manager', 'Trip Organizer',
    'Booking Manager', 'Finance Manager', 'Customer Support', 'Marketing Manager', 'Operations Manager',
    'Analytics Viewer',
)


def copy_legacy_roles(apps, schema_editor):
    Tenant = apps.get_model('tenancy', 'Tenant')
    TenantMembership = apps.get_model('tenancy', 'TenantMembership')
    Group = apps.get_model('auth', 'Group')
    connection = schema_editor.connection
    tenant_ids = list(Tenant.objects.values_list('pk', flat=True))
    with connection.cursor() as cursor:
        for tenant_id in tenant_ids:
            # RLS is enabled on memberships and the user/group through table.
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)])
            memberships = TenantMembership.objects.filter(
                tenant_id=tenant_id,
                role__in=('STAFF', 'TENANT_ADMIN'),
            ).only('pk', 'user_id', 'role')
            for membership in memberships.iterator():
                role = Group.objects.filter(
                    user__pk=membership.user_id,
                    name__in=LEGACY_STAFF_ROLES,
                ).order_by('name').values_list('name', flat=True).first()
                if role is None and membership.role == 'TENANT_ADMIN':
                    role = 'Admin'
                if role:
                    TenantMembership.objects.filter(pk=membership.pk).update(staff_role=role)


class Migration(migrations.Migration):
    dependencies = [
        ('tenancy', '0003_enable_tenant_rls'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantmembership',
            name='staff_role',
            field=models.CharField(blank=True, choices=[
                ('Super Admin', 'Super Admin'), ('Admin', 'Admin'), ('Content Manager', 'Content Manager'),
                ('Content Writer', 'Content Writer'), ('Trip Manager', 'Trip Manager'), ('Trip Organizer', 'Trip Organizer'),
                ('Booking Manager', 'Booking Manager'), ('Finance Manager', 'Finance Manager'),
                ('Customer Support', 'Customer Support'), ('Marketing Manager', 'Marketing Manager'),
                ('Operations Manager', 'Operations Manager'), ('Analytics Viewer', 'Analytics Viewer'),
            ], default='', max_length=80),
        ),
        migrations.RunPython(copy_legacy_roles, migrations.RunPython.noop),
    ]
