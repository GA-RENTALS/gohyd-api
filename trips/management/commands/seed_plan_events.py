"""Seed the 50 homepage plan cards as published Events with full page content and no dates ("Upcoming").

Each plan card on the homepage links to /events/<slug>; once the Event exists the card opens this content.
Content lives in trips/seed_data/plan_events.py. No schedule is created, so the page shows "Upcoming" and the
WhatsApp enquiry button until staff add a date and price in the admin panel.

Idempotent: re-running updates the title/summary/body but leaves page sections that already have rows alone,
so staff edits survive. Pass --refresh-content to replace the sections with the seed copy.
Events that staff have already given a date, price or cover are never touched for those fields.

Cover photos: trips/seed_assets/plan_events/<slug>.jpg (Wikimedia Commons, licences and credits in credits.json) are
uploaded to file storage (S3) for every event that has no cover yet, with the credit line on the media asset. This
needs S3: run it on the server (instance role) or with AWS keys in .env. Without S3 the photos are skipped with a
warning, and the website keeps showing the plan card photo.

Usage:  python manage.py seed_plan_events [--tenant gohyderabad] [--refresh-content] [--dry-run]
                                          [--images-only] [--skip-images]
"""
import json
import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from content.models import ContentStatus, MediaAsset
from tenancy.context import tenant_scope
from tenancy.models import Tenant
from trips.models import (Event, EventExclusion, EventFAQ, EventFormatDetail, EventHighlight, EventInclusion,
                          EventItinerary, EventItineraryItem, EventRegistrationType, EventRule, EventThingToBring,
                          EventTranslation, TripCategory)
from trips.seed_data.plan_events import PLAN_EVENTS

IMAGES = Path(__file__).resolve().parents[2] / 'seed_assets' / 'plan_events'
WHATSAPP = '+91 90593 38727'   # same booking number as the Box Cricket event

CATEGORY_NAMES = {
    'trekking': 'Trekking', 'forts': 'Forts', 'day-trips': 'Day Trips', 'camping': 'Camping', 'rides': 'Rides',
    'lakes': 'Lakes', 'adventure': 'Adventure', 'wildlife': 'Wildlife', 'waterfalls': 'Waterfalls',
    'temples': 'Temples', 'viewpoints': 'Viewpoints',
}

BRING_BASE = ['Personal water bottle (at least 2 litres).', 'Light snacks and energy bars.',
              'Comfortable clothes suited to the weather.', 'Cap, sunglasses and sunscreen.',
              'Government photo ID.', 'Any personal medicines.']
BRING_BY_CAT = {
    'trekking': ['Trekking or sports shoes with good grip.', 'A small backpack.'],
    'forts': ['Trekking or sports shoes with good grip.', 'A small backpack.'],
    'adventure': ['Sports shoes with good grip.', 'Clothes you can move freely in.'],
    'camping': ['A warm layer or jacket for the night.', 'Torch or headlamp.', 'Toiletries and a small towel.',
                'An extra set of clothes.'],
    'waterfalls': ['Shoes or sandals with good grip for wet rocks.', 'An extra set of clothes and a towel.'],
    'wildlife': ['Neutral-coloured clothes (avoid bright colours on safari).', 'Binoculars if you have them.',
                 'Clothes and toiletries for the stay.'],
    'temples': ['Modest clothing suitable for temple visits.'],
    'rides': ['Rain cover for your luggage.'],
}
INCLUSIONS = ['Trip planning and coordination by the GoHyderabad team.', 'Group briefing and a trip lead on the day.',
              'Exact inclusions (transport, meals, entry fees) are confirmed when the date is announced.']
INCLUSIONS_BY_CAT = {
    'camping': ['Tent stay and campfire (details confirmed with the date).'],
    'adventure': ['Activity equipment and safety gear with trained instructors.'],
    'wildlife': ['Safari booking assistance (subject to forest permits).'],
}
EXCLUSIONS = ['Personal expenses and shopping.', 'Anything not listed under inclusions.',
              'Costs from changes caused by weather, road or forest-department closures.']
RULES = ['Arrive on time at the meeting point.', 'Follow the instructions of the trip lead at all times.',
         'No alcohol or smoking during the activity.', 'Do not litter — carry back everything you bring.',
         'Respect local people, places of worship and wildlife.']
RULES_BY_CAT = {
    'waterfalls': ['Enter the water only where the trip lead says it is safe.'],
    'lakes': ['Wear a life jacket for any boating.'],
    'wildlife': ['Stay inside the vehicle on safari and keep quiet near animals.'],
    'rides': ['Helmets are mandatory. Ride in formation and do not overtake the lead rider.'],
    'adventure': ['Use the safety gear as instructed and follow the instructor at all times.'],
}
FAQS_BASE = [
    ('When is the next date?', 'This trip is upcoming. Message us on WhatsApp to register your interest and we '
                               'will let you know as soon as the date is announced.'),
    ('Can I come alone?', 'Yes. Many people join solo — it is a great way to meet the GoHyderabad community.'),
    ('Is it suitable for beginners?', 'Check the difficulty in the format section. Ask us on WhatsApp if you are unsure.'),
    ('What does it cost?', 'The price is shared when the date is announced. Message us on WhatsApp to know more.'),
]


def plan_slug(title: str) -> str:
    """Same as planSlug() in gohyd-ui/components/site/plan-slug.ts, so plan cards link to these events."""
    s = unicodedata.normalize('NFKD', title)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch)).lower().replace('&', ' and ')
    return re.sub(r'^-|-$', '', re.sub(r'[^a-z0-9]+', '-', s))


class Command(BaseCommand):
    help = 'Create/refresh the 50 homepage plans as published, undated ("Upcoming") Events with full page content.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad')
        parser.add_argument('--refresh-content', action='store_true',
                            help='Replace the page sections with the seed copy, even if staff edited them.')
        parser.add_argument('--dry-run', action='store_true', help='List what would be created; write nothing.')
        parser.add_argument('--images-only', action='store_true', help='Only upload missing cover photos.')
        parser.add_argument('--skip-images', action='store_true', help='Do not upload cover photos.')

    def handle(self, *args, **o):
        tenant = Tenant.objects.filter(slug=o['tenant']).first()
        if tenant is None:
            raise CommandError(f"No tenant '{o['tenant']}'.")
        slugs = [plan_slug(p['title']) for p in PLAN_EVENTS]
        if len(set(slugs)) != len(slugs):
            raise CommandError('Duplicate slugs in the seed data.')

        with tenant_scope(tenant.pk):
            if o['dry_run']:
                existing = set(Event.objects.filter(slug__in=slugs).values_list('slug', flat=True))
                for s in slugs:
                    self.stdout.write(f"{'update' if s in existing else 'create'}  /events/{s}")
                self.stdout.write(f'{len(slugs)} events, {len(existing)} already exist.')
                return
            if not o['images_only']:
                created = 0
                for plan in PLAN_EVENTS:
                    with transaction.atomic():
                        created += self._seed(tenant, plan, o['refresh_content'])
                self.stdout.write(self.style.SUCCESS(
                    f'Seeded {len(PLAN_EVENTS)} plan events ({created} new, {len(PLAN_EVENTS) - created} updated), all '
                    f'published with no dates.'))
            if not o['skip_images']:
                self._covers(slugs)

    def _covers(self, slugs):
        """Upload the bundled photo as the cover of every plan event that has none yet (staff uploads are kept)."""
        if not settings.AWS_STORAGE_BUCKET_NAME:
            self.stdout.write(self.style.WARNING(
                'Cover photos skipped: S3 is not configured here (AWS_STORAGE_BUCKET_NAME is empty). Run '
                '`python manage.py seed_plan_events --images-only` on the server, or add the AWS settings to .env.'))
            return
        credits = json.loads((IMAGES / 'credits.json').read_text())
        uploaded = kept = missing = 0
        for event in Event.objects.filter(slug__in=slugs).select_related('cover'):
            info = credits.get(event.slug)
            path = IMAGES / f'{event.slug}.jpg'
            if event.cover_id:
                kept += 1
                continue
            if not info or not path.exists():
                missing += 1
                self.stdout.write(self.style.WARNING(f'No bundled photo for {event.slug}.'))
                continue
            asset = MediaAsset(kind='image', alt_text=info['alt'][:255], credit=info['credit'][:255],
                               width=info['width'], height=info['height'])
            try:
                with path.open('rb') as fh:
                    asset.file.save(f'plan-events/{event.slug}.jpg', File(fh), save=False)
            except Exception as exc:   # noqa: BLE001 - storage backends raise many types (boto, OS, network)
                raise CommandError(
                    f'Could not upload {path.name} to file storage ({type(exc).__name__}: {exc}). '
                    f'{uploaded} covers were uploaded before this; re-run with --images-only to continue.') from exc
            with transaction.atomic():
                asset.save()
                Event.objects.filter(pk=event.pk, cover__isnull=True).update(cover=asset)
            uploaded += 1
            self.stdout.write(f'  cover uploaded: {event.slug}')
        self.stdout.write(self.style.SUCCESS(
            f'Cover photos: {uploaded} uploaded, {kept} already had a cover, {missing} without a bundled photo.'))

    def _seed(self, tenant, p, refresh):
        cat = p['cat']
        category, _ = TripCategory.objects.get_or_create(slug=cat, defaults={'name': CATEGORY_NAMES.get(cat, cat.title())})
        slug = plan_slug(p['title'])
        event = Event.objects.filter(slug=slug).first()
        created = event is None
        if created:
            event = Event(slug=slug, price=0, registration_type=EventRegistrationType.BOTH)
        event.category = category
        event.venue_name = p['venue']
        event.venue_address = '' if p['region'] in p['venue'] else p['region']
        event.booking_whatsapp_number = event.booking_whatsapp_number or WHATSAPP
        event.show_in_popup = False
        event.is_featured = False
        event.save()

        EventTranslation.objects.update_or_create(event=event, language='en', defaults={
            'title': p['title'], 'summary': p['summary'],
            'body': ''.join(f'<p>{para}</p>' for para in p['body']),
            'headline': p.get('headline', ''),
            'image_caption': f"{CATEGORY_NAMES.get(cat, cat)} · {p['region']}",
            'format_note': 'Dates, price and final inclusions are shared when the trip is announced.',
            'schedule_note': 'Timings are indicative and may change with weather, road and forest conditions.',
            'status': ContentStatus.APPROVED, 'approved_at': timezone.now(),
        })

        def write(model, rows, build):
            qs = model.objects.filter(event=event)
            if refresh:
                qs.delete()
            elif qs.exists():
                return
            model.objects.bulk_create([build(i, row) for i, row in enumerate(rows)])

        def text_row(model):
            return lambda i, text: model(event=event, text_en=text, sort_order=i, tenant=tenant)

        fmt = [('Status', 'Upcoming'), ('Type', CATEGORY_NAMES.get(cat, cat)), ('Region', p['region']),
               ('Distance from Hyderabad', p['km']), ('Duration', p['duration']), ('Difficulty', p['difficulty']),
               ('Best season', p['best'])]
        write(EventHighlight, p['highlights'], text_row(EventHighlight))
        write(EventThingToBring, BRING_BASE + BRING_BY_CAT.get(cat, []) + p.get('extra_bring', []), text_row(EventThingToBring))
        write(EventInclusion, INCLUSIONS + INCLUSIONS_BY_CAT.get(cat, []), text_row(EventInclusion))
        write(EventExclusion, EXCLUSIONS, text_row(EventExclusion))
        write(EventRule, RULES + RULES_BY_CAT.get(cat, []), text_row(EventRule))
        write(EventFormatDetail, fmt, lambda i, row: EventFormatDetail(
            event=event, label_en=row[0], value_en=row[1][:160], sort_order=i, tenant=tenant))
        write(EventFAQ, p.get('faqs', []) + FAQS_BASE, lambda i, row: EventFAQ(
            event=event, question_en=row[0], answer_en=row[1], sort_order=i, tenant=tenant))

        if refresh or not event.itineraries.exists():
            event.itineraries.all().delete()
            day = EventItinerary.objects.create(event=event, day_number=1, title_en='Plan for the day'
                                                if 'Overnight' not in p['duration'] and 'days' not in p['duration']
                                                else 'Trip plan')
            EventItineraryItem.objects.bulk_create([
                EventItineraryItem(itinerary=day, time_label=f'Stop {i + 1}', text_en=title, detail_en=detail,
                                   sort_order=i, tenant=tenant)
                for i, (title, detail) in enumerate(p['stops'])])

        event.refresh_from_db()
        event.publish()  # also (re)publishes the English translation updated above
        return int(created)
