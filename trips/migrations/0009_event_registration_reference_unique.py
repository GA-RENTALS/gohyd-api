import trips.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0008_backfill_event_registration_reference'),
    ]

    operations = [
        migrations.AlterField(
            model_name='eventregistration',
            name='reference',
            field=models.CharField(default=trips.models._new_event_reference, editable=False, max_length=16, unique=True),
        ),
    ]
