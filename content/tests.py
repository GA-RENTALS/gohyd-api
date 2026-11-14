import argparse

from django.core.exceptions import ValidationError
from core.testing import TenantTestCase
from django.test import TestCase
from rest_framework.test import APIClient

from content.management.commands.import_frontend_content import Command as ImportFrontendContentCommand
from .models import ContentStatus, Destination, DestinationTranslation


class PublishGateTests(TenantTestCase):
    def make(self, langs):
        d = Destination.objects.create(slug='ananthagiri')
        for l in langs:
            DestinationTranslation.objects.create(destination=d, language=l, title=f'T-{l}', status=ContentStatus.APPROVED)
        return d

    def test_publish_needs_only_english(self):
        d = self.make([])
        with self.assertRaises(ValidationError) as cm:
            d.publish()
        self.assertIn('English', cm.exception.messages[0])
        DestinationTranslation.objects.create(destination=d, language='en', title='Golconda')   # draft, never reviewed
        d.publish()
        d.refresh_from_db()
        self.assertEqual(d.status, ContentStatus.PUBLISHED)

    def test_missing_languages_fall_back_to_english(self):
        d = self.make([])
        DestinationTranslation.objects.create(destination=d, language='en', title='Golconda', summary='Old fort')
        d.publish()
        self.assertEqual(APIClient().get('/api/v1/destinations/?lang=hi').data['results'][0]['name'], 'Golconda')
        # a Telugu title added later shows straight away; its empty summary still falls back to English
        DestinationTranslation.objects.create(destination=d, language='te', title='గోల్కొండ')
        row = APIClient().get('/api/v1/destinations/?lang=te').data['results'][0]
        self.assertEqual((row['name'], row['summary']), ('గోల్కొండ', 'Old fort'))

    def test_publish_allowed_when_all_approved_and_public_api_shows_it(self):
        d = self.make(['en', 'te', 'hi'])
        d.publish()
        r = APIClient().get('/api/v1/destinations/?lang=te')
        self.assertEqual(r.data['results'][0]['name'], 'T-te')

    def test_draft_is_not_public(self):
        self.make(['en', 'te', 'hi'])
        self.assertEqual(APIClient().get('/api/v1/destinations/').data['count'], 0)

    def test_workflow_rejects_skipping_review(self):
        d = self.make([])
        t = DestinationTranslation.objects.create(destination=d, language='en', title='x')
        with self.assertRaises(ValidationError):
            t.move_to(ContentStatus.APPROVED)
        for step in (ContentStatus.SUBMITTED, ContentStatus.UNDER_REVIEW, ContentStatus.APPROVED):
            t.move_to(step)
        self.assertEqual(t.status, ContentStatus.APPROVED)


class ImportFrontendContentCommandTests(TestCase):
    def test_import_command_cannot_bypass_translation_approval(self):
        parser = argparse.ArgumentParser()
        ImportFrontendContentCommand().add_arguments(parser)
        option_strings = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        self.assertNotIn('--publish', option_strings)


class HomepageSiteSettingsTests(TenantTestCase):
    def test_stats_setting_is_created_with_defaults_and_editable(self):
        from rest_framework.test import APIClient
        from core.models import Setting
        r = APIClient().get('/api/v1/site-settings/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['homepage_stats']), 4)
        setting = Setting.objects.get(key='homepage.stats')
        setting.value = [{'value': 20, 'suffix': '+', 'label': 'Real number'}, {'value': 'oops', 'label': 'bad'}, 'junk']
        setting.save()
        stats = APIClient().get('/api/v1/site-settings/').data['homepage_stats']
        self.assertEqual(stats, [{'value': 20, 'label': 'Real number', 'suffix': '+', 'decimals': 0}])

    def test_only_allow_listed_settings_are_public(self):
        from rest_framework.test import APIClient
        from core.models import Setting
        Setting.objects.create(key='advance.default_basis_points', value=3000)
        self.assertEqual(set(APIClient().get('/api/v1/site-settings/').data), {'homepage_stats'})

    def test_only_published_testimonials_are_listed(self):
        from rest_framework.test import APIClient
        from .models import Testimonial
        Testimonial.objects.create(author_name='Shown', quote_en='Great', is_published=True)
        Testimonial.objects.create(author_name='Hidden', quote_en='Draft')
        names = [t['author_name'] for t in APIClient().get('/api/v1/testimonials/?lang=en').data]
        self.assertEqual(names, ['Shown'])


class UploadDestinationPhotosTests(TenantTestCase):
    """The photo upload command attaches covers and gallery photos, and is safe to run twice."""

    def test_command_sets_cover_and_gallery_and_is_idempotent(self):
        import tempfile
        from io import StringIO
        from django.core.management import call_command
        from django.test import override_settings
        from .models import Destination, DestinationMedia, DestinationTranslation, MediaAsset
        tmp = tempfile.mkdtemp()
        storage = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage', 'OPTIONS': {'location': tmp}},
                   'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
        # migration 0003 already seeds this destination, so reuse it rather than creating a duplicate slug
        d, _ = Destination.objects.get_or_create(slug='golconda-fort')
        DestinationTranslation.objects.update_or_create(destination=d, language='en', defaults={'title': 'Golconda Fort'})
        with override_settings(MEDIA_ROOT=tmp, STORAGES=storage, AWS_STORAGE_BUCKET_NAME=''):
            call_command('upload_destination_photos', '--allow-local', stdout=StringIO())
            call_command('upload_destination_photos', '--allow-local', stdout=StringIO())   # second run changes nothing
        d.refresh_from_db()
        self.assertEqual(d.cover.alt_text, 'Stone walls of Golconda Fort')
        self.assertEqual(DestinationMedia.objects.filter(destination=d).count(), 2)        # cover + gallery photo
        used = DestinationMedia.objects.filter(destination=d).values('asset')
        self.assertEqual(MediaAsset.objects.filter(pk__in=used, folder__name='Destination photos').count(), 2)   # no duplicates
        self.assertIn('Bernard Gagnon', d.cover.credit)                                   # photo credit kept with the image

    def test_command_refuses_without_s3_unless_allowed(self):
        from django.core.management import CommandError, call_command
        from django.test import override_settings
        with override_settings(AWS_STORAGE_BUCKET_NAME=''):
            with self.assertRaises(CommandError):
                call_command('upload_destination_photos')


class PublicListPageSizeTests(TenantTestCase):
    def test_lists_return_up_to_100_when_asked(self):
        from .models import Destination
        for i in range(15):
            Destination.objects.create(slug=f'place-{i}', status=ContentStatus.PUBLISHED)
        self.assertEqual(len(APIClient().get('/api/v1/destinations/').data['results']), 12)
        r = APIClient().get('/api/v1/destinations/?page_size=100').data
        self.assertEqual((len(r['results']), r['next']), (15, None))
        self.assertEqual(len(APIClient().get('/api/v1/destinations/?page_size=5000').data['results']), 15)   # capped at 100
