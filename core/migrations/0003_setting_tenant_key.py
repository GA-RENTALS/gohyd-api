import uuid

from django.db import migrations, models


def populate_setting_ids(apps, schema_editor):
    Setting = apps.get_model('core', 'Setting')
    alias = schema_editor.connection.alias
    # `key` is still the only unique column here, so update by key (a model save() can't locate the row).
    for key in list(Setting.objects.using(alias).filter(id__isnull=True).values_list('key', flat=True)):
        Setting.objects.using(alias).filter(key=key).update(id=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_auditlog_tenant_dataaccesslog_tenant_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='id',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='setting',
            name='key',
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(populate_setting_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='setting',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False),
        ),
        migrations.AddConstraint(
            model_name='setting',
            constraint=models.UniqueConstraint(fields=('tenant', 'key'), name='unique_tenant_setting_key'),
        ),
    ]
