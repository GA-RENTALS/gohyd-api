"""Copy files that only exist in the local media folder up to the configured storage (S3).

Use it once after switching on AWS_STORAGE_BUCKET_NAME, so photos and documents uploaded earlier keep working.
Safe to repeat: files that are already in storage are skipped.
"""
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import models

from tenancy.context import tenant_scope
from tenancy.models import Tenant


class Command(BaseCommand):
    help = 'Upload files from the local MEDIA_ROOT to the configured file storage (S3).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', default='gohyderabad')
        parser.add_argument('--dry-run', action='store_true', help='Only list what would be uploaded.')

    def handle(self, *args, **o):
        if not settings.AWS_STORAGE_BUCKET_NAME:
            raise CommandError('AWS_STORAGE_BUCKET_NAME is empty: files are already stored locally, nothing to upload.')
        try:
            tenant = Tenant.objects.get(slug=o['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant '{o['tenant']}'.")
        root = Path(settings.MEDIA_ROOT)
        counts = {'uploaded': 0, 'already there': 0, 'missing locally': 0}
        with tenant_scope(tenant.pk):
            for model in apps.get_models():
                fields = [f for f in model._meta.concrete_fields if isinstance(f, models.FileField)]
                for field in fields:
                    for name in model._default_manager.exclude(**{field.name: ''}).exclude(**{f'{field.name}__isnull': True}).values_list(field.name, flat=True):
                        local = root / name
                        try:
                            if default_storage.exists(name):
                                counts['already there'] += 1
                            elif not local.is_file():
                                counts['missing locally'] += 1
                                self.stderr.write(self.style.WARNING(f'  not found locally: {name} ({model.__name__}.{field.name})'))
                            elif o['dry_run']:
                                counts['uploaded'] += 1
                                self.stdout.write(f'  would upload {name}')
                            else:
                                with local.open('rb') as fh:
                                    saved = default_storage.save(name, File(fh))
                                if saved != name:
                                    self.stderr.write(self.style.WARNING(f'  stored as {saved} instead of {name}; update the record if the link is broken'))
                                counts['uploaded'] += 1
                        except Exception as exc:   # noqa: BLE001 - usually missing/invalid AWS credentials
                            raise CommandError(f'File storage is not reachable ({type(exc).__name__}: {exc}). Check the AWS settings in .env.') from exc
        label = 'Would upload' if o['dry_run'] else 'Uploaded'
        self.stdout.write(self.style.SUCCESS(f"{label} {counts['uploaded']}, already there {counts['already there']}, missing locally {counts['missing locally']}."))
