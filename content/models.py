"""Destinations, CMS, blogs, media, FAQs, testimonials, approval workflow (sections 8, 13.2, 13.10, 16)."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords
from tinymce.models import HTMLField

from core.models import Language, TenantBound, Timestamped, UUIDModel


class ContentStatus(models.TextChoices):
    """Section 16: Draft -> Submitted -> Under Review -> Changes Requested / Rejected -> Approved -> Published / Scheduled."""
    DRAFT = 'DRAFT'
    SUBMITTED = 'SUBMITTED'
    UNDER_REVIEW = 'UNDER_REVIEW'
    CHANGES_REQUESTED = 'CHANGES_REQUESTED'
    REJECTED = 'REJECTED'
    APPROVED = 'APPROVED'
    SCHEDULED = 'SCHEDULED'
    PUBLISHED = 'PUBLISHED'


# allowed workflow transitions
TRANSITIONS = {
    ContentStatus.DRAFT: {ContentStatus.SUBMITTED},
    ContentStatus.SUBMITTED: {ContentStatus.UNDER_REVIEW, ContentStatus.DRAFT},
    ContentStatus.UNDER_REVIEW: {ContentStatus.CHANGES_REQUESTED, ContentStatus.REJECTED, ContentStatus.APPROVED},
    ContentStatus.CHANGES_REQUESTED: {ContentStatus.SUBMITTED, ContentStatus.DRAFT},
    ContentStatus.REJECTED: {ContentStatus.DRAFT},
    ContentStatus.APPROVED: {ContentStatus.PUBLISHED, ContentStatus.SCHEDULED, ContentStatus.CHANGES_REQUESTED},
    ContentStatus.SCHEDULED: {ContentStatus.PUBLISHED, ContentStatus.APPROVED},
    ContentStatus.PUBLISHED: {ContentStatus.DRAFT},
}


class TranslationBase(Timestamped):
    """One row per language. Publishing the parent is blocked until EN, TE and HI are all APPROVED (section 8/16)."""
    language = models.CharField(max_length=2, choices=Language.choices)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    body = HTMLField(blank=True)
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=170, blank=True)
    localized_slug = models.SlugField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        abstract = True

    def move_to(self, new_status, user=None, note=''):
        if new_status not in TRANSITIONS.get(self.status, set()):
            raise ValidationError(f'Cannot move from {self.status} to {new_status}.')
        self.status = new_status
        if new_status == ContentStatus.APPROVED:
            self.approved_at, self.reviewed_by = timezone.now(), user
        if note:
            self.review_note = note
        self.save()


class Publishable(models.Model):
    """Mixin for a parent whose translations gate publication."""
    status = models.CharField(max_length=20, choices=ContentStatus.choices, default=ContentStatus.DRAFT, db_index=True)
    publish_at = models.DateTimeField(null=True, blank=True, help_text='If set (status Scheduled), goes live at this time.')
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def translation_rows(self):
        raise NotImplementedError

    def missing_approvals(self):
        approved = {t.language for t in self.translation_rows() if t.status in (ContentStatus.APPROVED, ContentStatus.PUBLISHED)}
        return [lang for lang, _ in Language.choices if lang not in approved]

    def publish(self, when=None):
        missing = self.missing_approvals()
        if missing:
            raise ValidationError(f'Cannot publish: approved translations missing for {", ".join(m.upper() for m in missing)}.')
        if when and when > timezone.now():
            self.status, self.publish_at = ContentStatus.SCHEDULED, when
        else:
            self.status, self.published_at = ContentStatus.PUBLISHED, timezone.now()
            self.translation_rows().filter(status=ContentStatus.APPROVED).update(status=ContentStatus.PUBLISHED)
        self.save()


class MediaFolder(Timestamped):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')

    class Meta:
        db_table = 'media_folders'

    def __str__(self):
        return self.name


class MediaAsset(UUIDModel, Timestamped):
    folder = models.ForeignKey(MediaFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name='assets')
    file = models.FileField(upload_to='media/%Y/%m/')
    kind = models.CharField(max_length=10, choices=[('image', 'Image'), ('video', 'Video'), ('doc', 'Document')], default='image')
    alt_text = models.CharField(max_length=255, blank=True)
    credit = models.CharField(max_length=255, blank=True, help_text='Photographer / licence line, e.g. "CC BY 4.0".')
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'media_assets'

    def __str__(self):
        return self.file.name


# ---- 13.2 Destinations ----
class DestinationCategory(Timestamped):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)   # English admin label; translations live in the translation tables

    class Meta:
        db_table = 'destination_categories'
        verbose_name_plural = 'destination categories'

    def __str__(self):
        return self.name


class Destination(UUIDModel, Timestamped, Publishable):
    slug = models.SlugField(unique=True)
    categories = models.ManyToManyField(DestinationCategory, blank=True, related_name='destinations')
    region = models.CharField(max_length=120, blank=True, help_text='e.g. Vikarabad district')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distance_km_from_city = models.PositiveIntegerField(null=True, blank=True)
    is_hyderabad_explore = models.BooleanField(default=False, help_text='Show in the Explore Hyderabad section/map.')
    cover = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sort_order = models.PositiveIntegerField(default=0)
    history = HistoricalRecords()

    class Meta:
        db_table = 'destinations'
        ordering = ['sort_order', 'slug']

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class DestinationTranslation(TranslationBase):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='translations')
    history = HistoricalRecords()

    class Meta:
        db_table = 'destination_translations'
        unique_together = ('destination', 'language')


class DestinationMedia(Timestamped):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='media')
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'destination_media'
        ordering = ['sort_order']


class DestinationActivity(Timestamped):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='activities')
    name = models.CharField(max_length=150)
    name_te = models.CharField(max_length=150, blank=True)
    name_hi = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = 'destination_activities'


class FAQ(Timestamped):
    """Used for destinations, trips and the site-wide FAQ page (leave both blank for site-wide)."""
    destination = models.ForeignKey(Destination, null=True, blank=True, on_delete=models.CASCADE, related_name='faqs')
    trip = models.ForeignKey('trips.Trip', null=True, blank=True, on_delete=models.CASCADE, related_name='faqs')
    question_en = models.CharField(max_length=300)
    answer_en = models.TextField()
    question_te = models.CharField(max_length=300, blank=True)
    answer_te = models.TextField(blank=True)
    question_hi = models.CharField(max_length=300, blank=True)
    answer_hi = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    class Meta:
        db_table = 'faqs'
        ordering = ['sort_order']


# ---- 13.10 CMS ----
class CmsPage(UUIDModel, Timestamped, Publishable):
    """Homepage, About, How it works, Corporate outings, Contact... (section 6). Homepage is manageable here."""
    slug = models.SlugField(unique=True)
    kind = models.CharField(max_length=30, default='page', help_text='homepage | about | how_it_works | corporate | contact | page')
    blocks_schema = models.JSONField(default=dict, blank=True, help_text='Structured homepage sections (hero, rails, etc.).')
    history = HistoricalRecords()

    class Meta:
        db_table = 'cms_pages'

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class CmsPageTranslation(TranslationBase):
    page = models.ForeignKey(CmsPage, on_delete=models.CASCADE, related_name='translations')
    blocks = models.JSONField(default=dict, blank=True, help_text='Translated values for blocks_schema keys.')
    history = HistoricalRecords()

    class Meta:
        db_table = 'content_translations'
        unique_together = ('page', 'language')


class BlogCategory(Timestamped):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = 'blog_categories'
        verbose_name_plural = 'blog categories'

    def __str__(self):
        return self.name


class BlogTag(TenantBound):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=60)

    class Meta:
        db_table = 'blog_tags'

    def __str__(self):
        return self.name


class Blog(UUIDModel, Timestamped, Publishable):
    slug = models.SlugField(unique=True)
    category = models.ForeignKey(BlogCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='blogs')
    tags = models.ManyToManyField(BlogTag, blank=True, related_name='blogs')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='blogs')
    cover = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    history = HistoricalRecords()

    class Meta:
        db_table = 'blogs'
        ordering = ['-published_at', '-created_at']

    def translation_rows(self):
        return self.translations.all()

    def __str__(self):
        return self.slug


class BlogTranslation(TranslationBase):
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='translations')
    history = HistoricalRecords()

    class Meta:
        db_table = 'blog_translations'
        unique_together = ('blog', 'language')


class Testimonial(Timestamped):
    author_name = models.CharField(max_length=120)
    author_role = models.CharField(max_length=120, blank=True)
    quote_en = models.TextField()
    quote_te = models.TextField(blank=True)
    quote_hi = models.TextField(blank=True)
    trip = models.ForeignKey('trips.Trip', null=True, blank=True, on_delete=models.SET_NULL, related_name='testimonials')
    is_published = models.BooleanField(default=False)

    class Meta:
        db_table = 'testimonials'


class Gallery(Timestamped):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)

    class Meta:
        db_table = 'galleries'
        verbose_name_plural = 'galleries'

    def __str__(self):
        return self.name


class GalleryItem(TenantBound):
    gallery = models.ForeignKey(Gallery, on_delete=models.CASCADE, related_name='items')
    asset = models.ForeignKey(MediaAsset, on_delete=models.CASCADE)
    caption = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'gallery_items'
        ordering = ['sort_order']


class SeoMetadata(Timestamped):
    """Section 13.2 destination_seo and general SEO management: per path, per language."""
    path = models.CharField(max_length=300)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.EN)
    title = models.CharField(max_length=70, blank=True)
    description = models.CharField(max_length=170, blank=True)
    og_image = models.ForeignKey(MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    canonical_url = models.URLField(blank=True)
    no_index = models.BooleanField(default=False)

    class Meta:
        db_table = 'seo_metadata'
        unique_together = ('path', 'language')


class PublishingSchedule(UUIDModel):
    """Scheduled go-live; content.tasks.publish_due flips SCHEDULED content to PUBLISHED."""
    content_type = models.CharField(max_length=30)  # destination | blog | page | trip
    object_id = models.CharField(max_length=64)
    publish_at = models.DateTimeField(db_index=True)
    done = models.BooleanField(default=False)

    class Meta:
        db_table = 'publishing_schedules'
