from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('crm', '0006_coupon_events_alter_coupon_trips'),
    ]

    operations = [
        migrations.AlterField(
            model_name='corporateenquiry',
            name='status',
            field=models.CharField(
                choices=[('NEW', 'New'), ('CONTACTED', 'Contacted'), ('QUALIFIED', 'Qualified'),
                         ('CONVERTED', 'Converted'), ('LOST', 'Lost')],
                db_index=True, default='NEW', max_length=12,
            ),
        ),
    ]
