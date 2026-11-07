from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from . import models as m


class ApprovalActionsMixin:
    """Admin actions for the section 16 workflow, applied to translation rows."""
    actions = ['submit_for_review', 'start_review', 'approve', 'request_changes', 'reject']

    def _move(self, request, qs, status):
        done = 0
        for t in qs:
            try:
                t.move_to(status, user=request.user)
                done += 1
            except ValidationError as e:
                self.message_user(request, f'{t}: {e.messages[0]}', messages.ERROR)
        if done:
            self.message_user(request, f'{done} moved to {status}.')

    @admin.action(description='Submit for review')
    def submit_for_review(self, request, qs): self._move(request, qs, m.ContentStatus.SUBMITTED)
    @admin.action(description='Start review')
    def start_review(self, request, qs): self._move(request, qs, m.ContentStatus.UNDER_REVIEW)
    @admin.action(description='Approve')
    def approve(self, request, qs): self._move(request, qs, m.ContentStatus.APPROVED)
    @admin.action(description='Request changes')
    def request_changes(self, request, qs): self._move(request, qs, m.ContentStatus.CHANGES_REQUESTED)
    @admin.action(description='Reject')
    def reject(self, request, qs): self._move(request, qs, m.ContentStatus.REJECTED)


class PublishableAdmin(SimpleHistoryAdmin, ModelAdmin):
    actions = ['publish_now']

    @admin.action(description='Publish (blocked until EN, TE and HI are approved)')
    def publish_now(self, request, qs):
        for obj in qs:
            try:
                obj.publish()
                self.message_user(request, f'{obj} published.')
            except ValidationError as e:
                self.message_user(request, f'{obj}: {e.messages[0]}', messages.ERROR)


def translation_inline(model):
    class Inline(StackedInline):
        extra = 0
        fields = ('language', 'title', 'summary', 'body', 'seo_title', 'seo_description', 'localized_slug', 'status', 'review_note')
    Inline.model = model
    return Inline


@admin.register(m.Destination)
class DestinationAdmin(PublishableAdmin):
    list_display = ('slug', 'region', 'status', 'is_hyderabad_explore', 'sort_order')
    list_filter = ('status', 'is_hyderabad_explore', 'categories')
    search_fields = ('slug', 'region', 'translations__title')
    inlines = [translation_inline(m.DestinationTranslation)]


@admin.register(m.DestinationTranslation)
class DestinationTranslationAdmin(ApprovalActionsMixin, SimpleHistoryAdmin, ModelAdmin):
    list_display = ('destination', 'language', 'title', 'status', 'approved_at')
    list_filter = ('language', 'status')


@admin.register(m.CmsPage)
class CmsPageAdmin(PublishableAdmin):
    list_display = ('slug', 'kind', 'status')
    inlines = [translation_inline(m.CmsPageTranslation)]


@admin.register(m.CmsPageTranslation)
class CmsPageTranslationAdmin(ApprovalActionsMixin, SimpleHistoryAdmin, ModelAdmin):
    list_display = ('page', 'language', 'title', 'status')
    list_filter = ('language', 'status')


@admin.register(m.Blog)
class BlogAdmin(PublishableAdmin):
    list_display = ('slug', 'category', 'status', 'published_at')
    list_filter = ('status', 'category')
    inlines = [translation_inline(m.BlogTranslation)]


@admin.register(m.BlogTranslation)
class BlogTranslationAdmin(ApprovalActionsMixin, SimpleHistoryAdmin, ModelAdmin):
    list_display = ('blog', 'language', 'title', 'status')
    list_filter = ('language', 'status')


for model in (m.DestinationCategory, m.BlogCategory, m.BlogTag, m.MediaFolder, m.Gallery, m.SeoMetadata, m.PublishingSchedule,
              m.DestinationActivity, m.DestinationMedia):
    admin.site.register(model, type(f'{model.__name__}Admin', (ModelAdmin,), {}))


@admin.register(m.MediaAsset)
class MediaAssetAdmin(ModelAdmin):
    list_display = ('file', 'kind', 'alt_text', 'folder', 'created_at')
    list_filter = ('kind', 'folder')
    search_fields = ('file', 'alt_text')


@admin.register(m.FAQ)
class FAQAdmin(ModelAdmin):
    list_display = ('question_en', 'destination', 'trip', 'is_published')
    list_filter = ('is_published',)


@admin.register(m.Testimonial)
class TestimonialAdmin(ModelAdmin):
    list_display = ('author_name', 'trip', 'is_published')
    list_filter = ('is_published',)
