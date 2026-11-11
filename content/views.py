from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import models as m
from . import serializers as s


class LangMixin:
    permission_classes = [AllowAny]
    lookup_field = 'slug'

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        lang = self.request.query_params.get('lang', 'en')
        ctx['lang'] = lang if lang in ('en', 'te', 'hi') else 'en'
        return ctx


class DestinationViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = s.DestinationSerializer
    filterset_fields = ['is_hyderabad_explore', 'categories__slug']
    search_fields = ['slug', 'region', 'translations__title']
    queryset = m.Destination.objects.filter(status=m.ContentStatus.PUBLISHED).select_related('cover').prefetch_related('translations')


class BlogViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = s.BlogSerializer
    filterset_fields = ['category__slug', 'tags__slug']
    queryset = m.Blog.objects.filter(status=m.ContentStatus.PUBLISHED).prefetch_related('translations')


class CmsPageViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = s.CmsPageSerializer
    pagination_class = None
    queryset = m.CmsPage.objects.filter(status=m.ContentStatus.PUBLISHED).prefetch_related('translations')


class FAQViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = s.FAQSerializer
    pagination_class = None
    filterset_fields = ['destination__slug', 'trip__slug']
    queryset = m.FAQ.objects.filter(is_published=True)
    lookup_field = 'pk'

    def get_queryset(self):
        queryset = super().get_queryset()
        # The public FAQ page shows only site-wide entries by default. Scoped FAQs
        # remain available when a destination or trip is explicitly requested.
        if self.action == 'list' and not self.request.query_params.get('destination__slug') and not self.request.query_params.get('trip__slug'):
            queryset = queryset.filter(destination__isnull=True, trip__isnull=True)
        return queryset


class TestimonialViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = s.TestimonialSerializer
    pagination_class = None
    queryset = m.Testimonial.objects.filter(is_published=True)
    lookup_field = 'pk'


class SiteSettingsView(APIView):
    """Public homepage values edited in Business settings (only allow-listed keys; see content/site_settings.py)."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from .site_settings import clean_stats, ensure_homepage_stats
        return Response({'homepage_stats': clean_stats(ensure_homepage_stats().value)})
