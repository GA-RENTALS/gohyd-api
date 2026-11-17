"""Blog posts in the staff admin: a card list with "Add blog post", and one page per post.

Creating a post needs only a title: the post and its English text are made together, so a post always has the
English row that publishing requires. Everything else on the post page is saved through the generic resources
(`blogs` for cover, category, tags and address; `blog-translations` for each language's text), which already check
permissions and write the audit log. Publishing goes through the existing content-transition action.
"""
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import Blog, BlogCategory, BlogTag, BlogTranslation, ContentStatus
from content.serializers import media_url

from .permissions import StaffOnly, staff_has_perm
from .views import _audit, _require_model_permission, _resolve, _serialize

LANGUAGES = ('en', 'te', 'hi')
LIVE = (ContentStatus.PUBLISHED, ContentStatus.SCHEDULED)


def _iso(v):
    return v.isoformat() if v else None


def _can(request, key, action='view'):
    try:
        _require_model_permission(request, _resolve(key), action)
        return True
    except Exception:   # noqa: BLE001 - PermissionDenied: hide that control
        return False


def _texts(blog):
    return {t.language: t for t in blog.translations.all()}


def _title(blog, texts=None):
    texts = texts if texts is not None else _texts(blog)
    row = texts.get('en') or next(iter(texts.values()), None)
    return row.title if row and row.title else blog.slug.replace('-', ' ').title()


def unique_slug(title):
    """A web address from the title: "Monsoon treks!" -> monsoon-treks, then monsoon-treks-2 if that is taken."""
    max_len = Blog._meta.get_field('slug').max_length
    base = slugify(title)[:max_len - 4].strip('-') or 'post'
    slug, n = base, 2
    while Blog.objects.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug


class BlogCatalogView(APIView):
    """GET: every post as a card, newest first. POST {title}: a new draft post with its English title."""
    permission_classes = [StaffOnly]

    def get(self, request):
        _require_model_permission(request, _resolve('blogs'), 'view')
        posts = (Blog.objects.select_related('cover', 'category', 'author').prefetch_related('translations')
                 .order_by('-updated_at'))
        q = request.query_params.get('search', '').strip()
        if q:
            posts = posts.filter(Q(slug__icontains=q) | Q(translations__title__icontains=q)).distinct()
        results = []
        for blog in posts[:200]:
            texts = _texts(blog)
            en = texts.get('en')
            results.append({
                'id': str(blog.pk), 'slug': blog.slug, 'title': _title(blog, texts), 'summary': en.summary if en else '',
                'status': blog.status, 'published_at': _iso(blog.published_at), 'updated_at': _iso(blog.updated_at),
                'cover_url': media_url(blog.cover, request), 'category': blog.category.name if blog.category else None,
                'languages': [code for code in LANGUAGES if code in texts],
                'author': (blog.author.full_name or blog.author.phone_number) if blog.author else None,
            })
        return Response({'results': results, 'can_create': self._can_create(request)})

    def post(self, request):
        if not self._can_create(request):
            return Response({'detail': 'You do not have permission to add blog posts.'}, status=status.HTTP_403_FORBIDDEN)
        title = str(request.data.get('title', '')).strip()
        max_len = BlogTranslation._meta.get_field('title').max_length
        if not title:
            raise serializers.ValidationError({'title': 'Enter a title.'})
        if len(title) > max_len:
            raise serializers.ValidationError({'title': f'Keep the title under {max_len} characters.'})
        with transaction.atomic():
            blog = Blog.objects.create(slug=unique_slug(title), author=request.user)
            BlogTranslation.objects.create(blog=blog, language='en', title=title)
            _audit(request, 'blogs.create', _resolve('blogs'), blog, after=_serialize(_resolve('blogs'), blog, request))
        return Response({'id': str(blog.pk), 'slug': blog.slug}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _can_create(request):
        # The generic `blogs` resource is edit-only, so creating is checked here against the model permissions.
        return staff_has_perm(request, 'content.add_blog') and staff_has_perm(request, 'content.add_blogtranslation')


class BlogOverviewView(APIView):
    """GET: everything the post page shows. DELETE: remove a post that is not on the website."""
    permission_classes = [StaffOnly]

    def _get(self, pk):
        try:
            return Blog.objects.select_related('cover', 'category', 'author').prefetch_related('translations', 'tags').get(pk=pk)
        except (Blog.DoesNotExist, ValueError, TypeError, Exception):   # noqa: BLE001 - malformed UUIDs raise ValidationError
            raise Http404('Blog post not found.')

    def get(self, request, pk):
        _require_model_permission(request, _resolve('blogs'), 'view')
        blog = self._get(pk)
        texts = _texts(blog)
        return Response({
            'id': str(blog.pk), 'slug': blog.slug, 'title': _title(blog, texts), 'status': blog.status,
            'published_at': _iso(blog.published_at), 'updated_at': _iso(blog.updated_at),
            # Once published, the address is shared and indexed, so it can't change (Publishable._keep_published_slug).
            'slug_locked': bool(blog.published_at),
            'cover': str(blog.cover_id) if blog.cover_id else None, 'cover_url': media_url(blog.cover, request),
            'category': blog.category_id, 'tags': [t.pk for t in blog.tags.all()],
            'author': (blog.author.full_name or blog.author.phone_number) if blog.author else None,
            'translations': {
                code: {'id': t.pk, 'title': t.title, 'summary': t.summary, 'body': t.body,
                       'seo_title': t.seo_title, 'seo_description': t.seo_description}
                for code, t in texts.items() if code in LANGUAGES
            },
            'options': {
                'categories': [{'id': c.pk, 'name': c.name} for c in BlogCategory.objects.order_by('name')],
                'tags': [{'id': t.pk, 'name': t.name} for t in BlogTag.objects.order_by('name')],
            },
            'limits': {f: BlogTranslation._meta.get_field(f).max_length for f in ('title', 'seo_title', 'seo_description')},
            'permissions': {
                'edit': _can(request, 'blogs', 'change'),
                'add_text': _can(request, 'blog-translations', 'add'),
                'edit_text': _can(request, 'blog-translations', 'change'),
                'delete_text': _can(request, 'blog-translations', 'delete'),
                'delete': staff_has_perm(request, 'content.delete_blog'),
            },
        })

    def delete(self, request, pk):
        if not staff_has_perm(request, 'content.delete_blog'):
            return Response({'detail': 'You do not have permission to delete blog posts.'}, status=status.HTTP_403_FORBIDDEN)
        blog = self._get(pk)
        if blog.status in LIVE:
            return Response({'detail': 'This post is on the website. Unpublish it first, then delete it.'}, status=status.HTTP_409_CONFLICT)
        resource = _resolve('blogs')
        before = _serialize(resource, blog, request)
        with transaction.atomic():
            _audit(request, 'blogs.delete', resource, blog, before=before)   # first, while the post still has its id
            blog.delete()   # its translations go with it (CASCADE)
        return Response(status=status.HTTP_204_NO_CONTENT)
