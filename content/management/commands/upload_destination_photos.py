"""Upload the destination photos in content/seed_assets/destinations/ to file storage (S3) and attach them.

File names say where each photo goes:
    golconda-fort.jpg      -> cover photo of the destination with slug "golconda-fort"
    golconda-fort--2.jpg   -> extra gallery photo for the same destination (shown 2nd)
Photographer and licence for each file are in content/seed_assets/destinations/credits.py and are saved with the photo.

Runs automatically on every deploy (see .github/workflows/deploy.yml). It is quick when there is nothing new:
photos already uploaded are reused, and a cover someone has set in the admin is never replaced (unless --replace-covers).
    python manage.py upload_destination_photos --dry-run     # show what would happen
    python manage.py upload_destination_photos               # upload and attach
"""
import importlib.util
import re
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image

from content.models import Destination, DestinationMedia, MediaAsset, MediaFolder
from tenancy.context import tenant_scope
from tenancy.models import Tenant

PHOTOS = Path(__file__).resolve().parents[2] / 'seed_assets' / 'destinations'
FOLDER = 'Destination photos'   # every photo this command uploads lives in this media-library folder


def _credits():
    spec = importlib.util.spec_from_file_location('destination_photo_credits', PHOTOS / 'credits.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Command(BaseCommand):
    help = 'Upload destination photos to S3 and set them as destination covers / gallery photos.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad')
        parser.add_argument('--dry-run', action='store_true', help='Only print what would happen.')
        parser.add_argument('--replace-covers', action='store_true', help='Also replace covers that are already set.')
        parser.add_argument('--allow-local', action='store_true', help='Save to local disk if S3 is not configured (not for production).')

    def handle(self, *args, **o):
        if not settings.AWS_STORAGE_BUCKET_NAME and not o['allow_local']:
            raise CommandError('AWS_STORAGE_BUCKET_NAME is not set, so files would be saved on this server\'s disk, not S3. '
                               'Set it (and give the server S3 access) or pass --allow-local.')
        tenant = Tenant.objects.filter(slug=o['tenant']).first()
        if tenant is None:
            raise CommandError(f"No tenant '{o['tenant']}'.")
        credits = _credits()
        files = sorted(PHOTOS.glob('*.jpg'))
        missing_credit = [p.name for p in files if p.name not in credits.PHOTOS]
        if missing_credit:
            raise CommandError(f'Add a credit line in credits.py for: {", ".join(missing_credit)}')

        with tenant_scope(tenant.pk):
            folder = MediaFolder.objects.filter(name=FOLDER, parent=None).first()
            plan = []
            for path in files:
                slug, _, n = path.stem.partition('--')
                position = int(n) if n else 1
                dest = Destination.objects.filter(slug=slug).first()
                if dest is None:
                    self.stdout.write(self.style.WARNING(f'skip   {path.name}: no destination "{slug}"'))
                    continue
                # storage may add a suffix when the name is taken (golconda-fort_Ab12cd3.jpg), so match with or without it
                pattern = rf'(^|/){re.escape(path.stem)}(_[A-Za-z0-9]{{7}})?\.jpg$'
                asset = MediaAsset.objects.filter(folder=folder, file__regex=pattern).first() if folder else None
                needs_cover = position == 1 and (dest.cover_id is None or o['replace_covers']) and (asset is None or dest.cover_id != asset.pk)
                needs_gallery = asset is None or not DestinationMedia.objects.filter(destination=dest, asset=asset).exists()
                plan.append((path, dest, position, asset, needs_cover, needs_gallery))

            todo = [p for p in plan if p[3] is None or p[4] or p[5]]
            if not todo:
                self.stdout.write(self.style.SUCCESS(f'Destination photos: all {len(plan)} already uploaded and attached. Nothing to do.'))
                return
            if o['dry_run']:
                for path, dest, position, asset, needs_cover, _ in todo:
                    role = 'cover' if position == 1 else f'gallery #{position}'
                    self.stdout.write(f'{"reuse" if asset else "upload":6} {path.name:40} -> {dest.slug} ({role}{", set as cover" if needs_cover else ""})')
                self.stdout.write(self.style.SUCCESS(f'Dry run: {len(todo)} of {len(plan)} photos need work. Nothing was changed.'))
                return
            if settings.AWS_STORAGE_BUCKET_NAME and any(p[3] is None for p in todo):
                self._check_s3()

            folder = folder or MediaFolder.objects.create(name=FOLDER)
            uploaded = covers = gallery = 0
            for path, dest, position, asset, needs_cover, needs_gallery in todo:
                with transaction.atomic():
                    if asset is None:
                        with Image.open(path) as im:
                            width, height = im.size
                        asset = MediaAsset(kind='image', folder=folder, alt_text=credits.alt_text(path.name),
                                           credit=credits.credit_line(path.name), width=width, height=height)
                        with path.open('rb') as fh:
                            asset.file.save(f'destinations/{path.name}', File(fh), save=False)
                        asset.full_clean()
                        asset.save()
                        uploaded += 1
                    if position == 1 and (dest.cover_id is None or o['replace_covers']) and dest.cover_id != asset.pk:
                        dest.cover = asset
                        dest.save(update_fields=['cover', 'updated_at'])
                        covers += 1
                    _, made = DestinationMedia.objects.get_or_create(destination=dest, asset=asset, defaults={'sort_order': position})
                    gallery += made
                self.stdout.write(f'ok     {path.name:40} -> {asset.file.url}')

        self.stdout.write(self.style.SUCCESS(f'Destination photos: {uploaded} uploaded, {covers} covers set, {gallery} gallery photos attached.'))

    def _check_s3(self):
        """Fail early with a clear message instead of half-way through."""
        try:
            name = default_storage.save('destinations/.upload-check', ContentFile(b'ok'))
            default_storage.delete(name)
        except Exception as exc:   # noqa: BLE001 - any storage/credential error
            raise CommandError(f'Cannot write to S3 bucket "{settings.AWS_STORAGE_BUCKET_NAME}": {exc}. '
                               'On the server this needs an IAM role (or AWS keys) with s3:PutObject on the bucket.') from exc
