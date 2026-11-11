import trips.models
from django.db import migrations


def backfill_registrations(apps, schema_editor):
    """Give existing rows a unique booking reference; legacy REGISTERED rows count as confirmed."""
    Registration = apps.get_model('trips', 'EventRegistration')
    used = set()
    for row in Registration.objects.all().only('pk', 'status'):
        ref = trips.models._new_event_reference()
        while ref in used:
            ref = trips.models._new_event_reference()
        used.add(ref)
        Registration.objects.filter(pk=row.pk).update(
            reference=ref, status='CONFIRMED' if row.status == 'REGISTERED' else row.status)


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0007_event_bookings_format_rules'),
    ]

    operations = [
        migrations.RunPython(backfill_registrations, migrations.RunPython.noop),
    ]
