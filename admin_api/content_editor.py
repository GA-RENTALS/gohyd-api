"""Blog posts, website pages and destinations in the staff admin: a card list with "Add", and one page per item.

The three share a shape (content.models.Publishable with per-language TranslationBase rows), so one editor serves them:

    GET  /admin/content/<kind>/            cards, newest first (?search=)        kind: blogs | pages | destinations
    POST /admin/content/<kind>/            {title[, slug]} -> a draft with its English text
    GET  /admin/content/<kind>/<id>/       everything the editor page shows
    DELETE /admin/content/<kind>/<id>/     remove one that is not on the website

Creating needs only a title: the item and its English text are made together, so it always has the English row that
publishing requires. Everything else is saved through the generic resources (the item's own resource for its fields,
the translation resource for each language's text), which already check permissions and write the audit log.
Publishing and scheduling go through the content-transition action.
"""
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import ProtectedError, Q, RestrictedError
from django.http import Http404
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import (Blog, BlogCategory, BlogTag, BlogTranslation, CmsPage, CmsPageTranslation, ContentStatus,
                            Destination, DestinationTranslation)
from content.serializers import media_url

from .permissions import StaffOnly, staff_has_perm
from .views import _audit, _require_model_permission, _resolve, _serialize

LANGUAGES = ('en', 'te', 'hi')

# Website pages the code itself shows at a fixed address (gohyd-ui app/(public)/(site)/[slug]/page.tsx). Their address
# can't be changed in the editor, or the page would stop showing.
FIXED_PAGE_SLUGS = frozenset({'about', 'how-it-works', 'faqs', 'contact', 'corporate', 'community', 'membership',
                              'privacy', 'terms', 'refund-policy', 'homepage'})


@dataclass(frozen=True)
class ContentKind:
    model: type
    translation: type
    parent_field: str           # the translation's foreign key to the item
    resource: str               # generic resource for the item's own fields
    text_resource: str          # generic resource for each language's text
    label: str                  # "blog post"
    public_prefix: str          # the item's address on the website, before its slug
    select_related: tuple = ()
    prefetch_related: tuple = field(default=('translations',))

    @property
    def perm(self):
        return f'{self.model._meta.app_label}.%s_{self.model._meta.model_name}'

    @property
    def text_perm(self):
        return f'{self.translation._meta.app_label}.%s_{self.translation._meta.model_name}'


KINDS = {
    'blogs': ContentKind(Blog, BlogTranslation, 'blog', 'blogs', 'blog-translations', 'blog post', '/blogs/',
                         select_related=('cover', 'category', 'author'), prefetch_related=('translations', 'tags')),
    'pages': ContentKind(CmsPage, CmsPageTranslation, 'page', 'cms-pages', 'cms-translations', 'page', '/'),
    'destinations': ContentKind(Destination, DestinationTranslation, 'destination', 'destinations', 'destination-translations',
                                'destination', '/destinations/', select_related=('cover',)),
}


def _kind(kind):
    try:
        return KINDS[kind]
    except KeyError:
        raise Http404('Unknown content type.')


def _iso(v):
    return v.isoformat() if v else None


def _can(request, key, action='view'):
    try:
        _require_model_permission(request, _resolve(key), action)
        return True
    except Exception:   # noqa: BLE001 - PermissionDenied: hide that control
        return False


def _texts(item):
    return {t.language: t for t in item.translations.all()}


def _title(item, texts=None):
    texts = texts if texts is not None else _texts(item)
    row = texts.get('en') or next(iter(texts.values()), None)
    return row.title if row and row.title else item.slug.replace('-', ' ').title()


def unique_slug(model, text):
    """A web address from the title: "Monsoon treks!" -> monsoon-treks, then monsoon-treks-2 if that is taken."""
    max_len = model._meta.get_field('slug').max_length
    base = slugify(text)[:max_len - 4].strip('-') or 'item'
    slug, n = base, 2
    while model.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


def _subtitle(spec, item):
    """The line under the title on a card: who/what it is at a glance."""
    if spec.model is Blog:
        return ' · '.join(filter(None, [item.category.name if item.category else '',
                                        (item.author.full_name or item.author.phone_number) if item.author else '']))
    if spec.model is Destination:
        return item.region
    return f'{spec.public_prefix}{item.slug}'


class ContentCatalogView(APIView):
    """GET: every item as a card, newest first. POST {title[, slug]}: a new draft with its English title."""
    permission_classes = [StaffOnly]

    def get(self, request, kind):
        spec = _kind(kind)
        _require_model_permission(request, _resolve(spec.resource), 'view')
        items = (spec.model.objects.select_related(*spec.select_related).prefetch_related('translations')
                 .order_by('-updated_at'))
        q = request.query_params.get('search', '').strip()
        if q:
            items = items.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()
        results = []
        for item in items[:300]:
            texts = _texts(item)
            en = texts.get('en')
            results.append({
                'id': str(item.pk), 'slug': item.slug, 'title': _title(item, texts), 'summary': en.summary if en else '',
                'status': item.status, 'publish_at': _iso(item.publish_at), 'published_at': _iso(item.published_at),
                'updated_at': _iso(item.updated_at), 'subtitle': _subtitle(spec, item),
                'cover_url': media_url(item.cover, request) if hasattr(item, 'cover') else None,
                'languages': [code for code in LANGUAGES if code in texts],
            })
        return Response({'results': results, 'can_create': self._can_create(request, spec),
                         'existing_slugs': sorted(spec.model.objects.values_list('slug', flat=True)) if kind == 'pages' else []})

    def post(self, request, kind):
        spec = _kind(kind)
        if not self._can_create(request, spec):
            return Response({'detail': f'You do not have permission to add a {spec.label}.'}, status=status.HTTP_403_FORBIDDEN)
        title = str(request.data.get('title', '')).strip()
        max_len = spec.translation._meta.get_field('title').max_length
        if not title:
            raise serializers.ValidationError({'title': 'Enter a title.'})
        if len(title) > max_len:
            raise serializers.ValidationError({'title': f'Keep the title under {max_len} characters.'})
        # Pages may ask for an exact address (privacy, terms…); otherwise it comes from the title.
        slug = slugify(str(request.data.get('slug', '')).strip())
        if slug and spec.model.objects.filter(slug=slug).exists():
            raise serializers.ValidationError({'slug': f'A {spec.label} already uses the address “{slug}”.'})
        resource = _resolve(spec.resource)
        with transaction.atomic():
            extra = {'author': request.user} if spec.model is Blog else {}
            item = spec.model.objects.create(slug=slug or unique_slug(spec.model, title), **extra)
            spec.translation.objects.create(**{spec.parent_field: item}, language='en', title=title)
            _audit(request, f'{spec.resource}.create', resource, item, after=_serialize(resource, item, request))
        return Response({'id': str(item.pk), 'slug': item.slug}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _can_create(request, spec):
        # Blogs and pages are edit-only in the generic resources, so creating is checked here against the model permissions.
        return staff_has_perm(request, spec.perm % 'add') and staff_has_perm(request, spec.text_perm % 'add')


class ContentOverviewView(APIView):
    """GET: everything the editor page shows. DELETE: remove an item that is not on the website."""
    permission_classes = [StaffOnly]

    @staticmethod
    def _get(spec, pk):
        try:
            return (spec.model.objects.select_related(*spec.select_related).prefetch_related(*spec.prefetch_related)
                    .get(pk=pk))
        except Exception:   # noqa: BLE001 - DoesNotExist, or a malformed id (ValidationError / ValueError)
            raise Http404(f'{spec.label.capitalize()} not found.')

    def get(self, request, kind, pk):
        spec = _kind(kind)
        _require_model_permission(request, _resolve(spec.resource), 'view')
        item = self._get(spec, pk)
        texts = _texts(item)
        data = {
            'kind': kind, 'id': str(item.pk), 'slug': item.slug, 'title': _title(item, texts), 'status': item.status,
            'publish_at': _iso(item.publish_at), 'published_at': _iso(item.published_at), 'updated_at': _iso(item.updated_at),
            'public_url': f'{spec.public_prefix}{item.slug}',
            # Once published, the address is shared and indexed, so it can't change (Publishable._keep_published_slug).
            'slug_locked': bool(item.published_at) or (spec.model is CmsPage and item.slug in FIXED_PAGE_SLUGS),
            'translations': {
                code: {'id': t.pk, 'title': t.title, 'summary': t.summary, 'body': t.body,
                       'seo_title': t.seo_title, 'seo_description': t.seo_description}
                for code, t in texts.items() if code in LANGUAGES
            },
            'limits': {f: spec.translation._meta.get_field(f).max_length for f in ('title', 'seo_title', 'seo_description')},
            'permissions': {
                'edit': _can(request, spec.resource, 'change'),
                'add_text': _can(request, spec.text_resource, 'add'),
                'edit_text': _can(request, spec.text_resource, 'change'),
                'delete_text': _can(request, spec.text_resource, 'delete'),
                'delete': staff_has_perm(request, spec.perm % 'delete'),
            },
        }
        if spec.model is Blog:
            data.update({
                'cover': str(item.cover_id) if item.cover_id else None, 'cover_url': media_url(item.cover, request),
                'category': item.category_id, 'tags': [t.pk for t in item.tags.all()],
                'author': (item.author.full_name or item.author.phone_number) if item.author else None,
                'options': {
                    'categories': [{'id': c.pk, 'name': c.name} for c in BlogCategory.objects.order_by('name')],
                    'tags': [{'id': t.pk, 'name': t.name} for t in BlogTag.objects.order_by('name')],
                },
            })
        return Response(data)

    def delete(self, request, kind, pk):
        spec = _kind(kind)
        if not staff_has_perm(request, spec.perm % 'delete'):
            return Response({'detail': f'You do not have permission to delete a {spec.label}.'}, status=status.HTTP_403_FORBIDDEN)
        item = self._get(spec, pk)
        if item.status == ContentStatus.SCHEDULED:
            return Response({'detail': f'This {spec.label} is scheduled to go live. Cancel the schedule first, then delete it.'},
                            status=status.HTTP_409_CONFLICT)
        if item.status == ContentStatus.PUBLISHED:
            return Response({'detail': f'This {spec.label} is on the website. Unpublish it first, then delete it.'},
                            status=status.HTTP_409_CONFLICT)
        resource = _resolve(spec.resource)
        before = _serialize(resource, item, request)
        try:
            with transaction.atomic():
                _audit(request, f'{spec.resource}.delete', resource, item, before=before)   # first, while it still has its id
                item.delete()   # its translations go with it (CASCADE)
        except (ProtectedError, RestrictedError):
            return Response({'detail': f'This {spec.label} is still used elsewhere (for example by a trip). Remove those links first.'},
                            status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)
