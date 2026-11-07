"""Import the content that was hard-coded in the public website into Django, so the admin panel manages it.

Idempotent: records that already exist (by slug / name) are left untouched, so edits made in the admin are never overwritten.
Everything is created as DRAFT unless --publish is given, so the live website does not change until you decide.
"""
import importlib
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from content import frontend_content as data
from content.models import ContentStatus, Destination, DestinationTranslation, MediaAsset, Testimonial
from core.models import Setting
from tenancy.context import tenant_scope
from tenancy.models import Tenant
from trips.models import Trip, TripCategory, TripCategoryLink, TripDestination, TripTranslation


class Command(BaseCommand):
    help = 'Import trips, categories, destination details, testimonials and site stats from the public website into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad', help='Tenant slug (default: gohyderabad).')
        parser.add_argument('--frontend-dir', default=str(Path(settings.BASE_DIR).parent / 'GoHyderabad'), help='Path to the Next.js project (for photos).')
        parser.add_argument('--publish', action='store_true', help='Publish trips and destinations (the public site will then render them from the API).')
        parser.add_argument('--dry-run', action='store_true', help='Do everything, then roll back.')

    def handle(self, *args, **o):
        try:
            tenant = Tenant.objects.get(slug=o['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant with slug '{o['tenant']}'.")
        img_dir = Path(o['frontend_dir']) / 'public' / 'assets' / 'img'
        if not img_dir.is_dir():
            self.stderr.write(self.style.WARNING(f'Photos folder not found ({img_dir}); content will be imported without cover images.'))
        self.publish, self.img_dir, self.counts = o['publish'], img_dir, {}
        self.status = ContentStatus.PUBLISHED if self.publish else ContentStatus.DRAFT
        self.now = timezone.now()
        self.assets = {}

        with tenant_scope(tenant.pk), transaction.atomic():
            self.import_categories()
            self.import_places()
            self.import_plans()
            self.import_testimonials()
            self.import_site_settings()
            if o['dry_run']:
                transaction.set_rollback(True)

        for k, (made, skipped) in self.counts.items():
            self.stdout.write(f'  {k:<14} created {made:>3}   already there {skipped:>3}')
        self.stdout.write(self.style.SUCCESS(('Dry run only, nothing saved.' if o['dry_run'] else 'Imported.')
                                             + (' Published.' if self.publish else ' Left as DRAFT; publish from the admin when ready.')))

    def tally(self, key, created):
        made, skipped = self.counts.get(key, (0, 0))
        self.counts[key] = (made + 1, skipped) if created else (made, skipped + 1)

    def asset(self, image, alt='', credit=''):
        """MediaAsset for a website photo (copied into media storage once)."""
        if image in self.assets:
            return self.assets[image]
        path = self.img_dir / image
        existing = MediaAsset.objects.filter(file__endswith=image).first()
        if existing:
            self.assets[image] = existing
            return existing
        if not path.is_file():
            self.assets[image] = None
            return None
        asset = MediaAsset(kind='image', alt_text=alt[:200], credit=credit[:200])
        target = asset.file.field.generate_filename(asset, image)
        if default_storage.exists(target):      # e.g. left behind by an earlier dry run: reuse, don't duplicate
            asset.file.name = target
        else:
            with path.open('rb') as fh:
                asset.file.save(image, File(fh), save=False)
        asset.save()
        self.tally('photos', True)
        self.assets[image] = asset
        return asset

    def find_destination(self, name):
        base = name.replace('–', '-').split(' - ')[0].strip()
        slug = slugify(base)
        dest = Destination.objects.filter(slug=slug).first()
        if dest:
            return dest
        for d in Destination.objects.all():
            if slug and (slug in d.slug or d.slug in slug):
                return d
        return None

    def import_categories(self):
        for order, (slug, name) in enumerate(data.CATEGORIES):
            _, created = TripCategory.objects.get_or_create(slug=slug, defaults={'name': name, 'sort_order': order})
            self.tally('categories', created)

    def import_places(self):
        """The eight 'Explore Hyderabad' places: richer descriptions, regions, photos and credits for the matching destinations."""
        for place in data.PLACES:
            dest = self.find_destination(place['name'])
            if dest is None:
                self.stderr.write(self.style.WARNING(f"  no destination matches place '{place['name']}', skipped"))
                continue
            changed = False
            cover = self.asset(place['image'], place['alt'], f"{place['credit']} ({place['credit_url']})".strip())
            if cover and dest.cover_id is None:
                dest.cover, changed = cover, True
            if not dest.region or dest.region != place['region']:
                dest.region, changed = place['region'], True
            if self.publish and dest.status != ContentStatus.PUBLISHED:
                dest.status, dest.published_at, changed = ContentStatus.PUBLISHED, self.now, True
            if changed:
                dest.save()
            tr, _ = DestinationTranslation.objects.get_or_create(destination=dest, language='en', defaults={'title': place['name'], 'status': self.status})
            if len(tr.summary) < len(place['summary']):
                tr.summary = place['summary']
                tr.title = tr.title or place['name']
                tr.save()
            self.tally('places', changed)
        if self.publish:   # the other imported map pins (the 53 from the seed migration) belong on the map too
            seeded = importlib.import_module('content.migrations.0003_seed_frontend_destinations').DESTINATIONS
            slugs = [slugify(row[0]) for row in seeded]
            for dest in Destination.objects.filter(slug__in=slugs).exclude(status=ContentStatus.PUBLISHED):
                dest.status, dest.published_at = ContentStatus.PUBLISHED, self.now
                dest.save()
                DestinationTranslation.objects.filter(destination=dest).update(status=ContentStatus.PUBLISHED)
                self.tally('destinations', True)

    def import_plans(self):
        categories = {c.slug: c for c in TripCategory.objects.all()}
        for order, plan in enumerate(data.PLANS):
            slug = slugify(plan['name'])
            trip, created = Trip.objects.get_or_create(slug=slug, defaults={
                'status': self.status, 'published_at': self.now if self.publish else None, 'sort_order': order,
                'cover': self.asset(plan['image'], plan['alt'])})
            self.tally('trips', created)
            if not created:
                if self.publish and trip.status != ContentStatus.PUBLISHED:   # an imported draft being published now
                    trip.status, trip.published_at = ContentStatus.PUBLISHED, self.now
                    trip.save()
                    TripTranslation.objects.filter(trip=trip).update(status=ContentStatus.PUBLISHED)
                    self.tally('trips published', True)
                continue
            TripTranslation.objects.create(trip=trip, language='en', title=plan['name'], summary=plan['summary'], status=self.status)
            if plan['category'] in categories:
                TripCategoryLink.objects.get_or_create(trip=trip, category=categories[plan['category']])
            dest = self.find_destination(plan['name'])
            if dest:
                TripDestination.objects.get_or_create(trip=trip, destination=dest)

    def import_testimonials(self):
        for t in data.TESTIMONIALS:
            # The website labels these quotes as placeholders, so they are never published automatically.
            _, created = Testimonial.objects.get_or_create(author_name=t['author'], quote_en=t['quote'], defaults={'author_role': t['role'], 'is_published': False})
            self.tally('testimonials', created)

    def import_site_settings(self):
        for key, value, desc in (
            ('site.stats', data.STATS, 'Headline numbers on the website ("12,500+ community members"). Marketing figures, review before relying on them.'),
            ('site.how_it_works', data.HOW_IT_WORKS, 'The three "how it works" steps on the website.'),
        ):
            _, created = Setting.objects.get_or_create(key=key, defaults={'value': value, 'description': desc})
            self.tally('settings', created)
