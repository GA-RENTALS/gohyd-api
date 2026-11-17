"""Storage for files with personal data (payment screenshots and proofs).

Ordinary uploads (trip photos) are public and cached for a year. These are not: on S3 each object is private and every
link is signed and expires after PRIVATE_FILE_URL_SECONDS, so a copied admin link stops working. The bucket policy must
not grant public read on these prefixes either (see the deployment notes: `event-payments/` and `payment_proofs/`).
Without S3 (local development) files stay on disk like any other upload.
"""
from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.functional import LazyObject, empty


class _PrivateStorage(LazyObject):
    """STORAGES['private'] (set in config/settings.py when S3 is configured), otherwise the default storage."""

    def _setup(self):
        from django.core.files.storage import storages
        self._wrapped = storages['private' if 'private' in settings.STORAGES else 'default']


_private = _PrivateStorage()


@receiver(setting_changed)
def _follow_storage_settings(*, setting, **kwargs):
    if setting == 'STORAGES':   # e.g. a test pointing uploads at a temporary folder
        _private._wrapped = empty


def private_storage():
    """For FileField(storage=private_storage): migrations record this function's path, not the settings it reads."""
    return _private
