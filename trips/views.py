from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from content.models import ContentStatus
from content.views import LangMixin
from . import models as m
from . import serializers as s


class TripViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    """Only editorially PUBLISHED trips are public; availability comes from operational_status / schedule.is_open."""
    filterset_fields = ['categories__slug', 'destinations__slug', 'operational_status']
    search_fields = ['slug', 'translations__title']
    ordering_fields = ['sort_order', 'created_at']
    queryset = (m.Trip.objects.filter(status=ContentStatus.PUBLISHED)
                .select_related('cover')
                .prefetch_related('translations', 'schedules', 'categories', 'pickup_points', 'inclusions', 'exclusions', 'policies').distinct())

    def get_serializer_class(self):
        return s.TripDetailSerializer if self.action == 'retrieve' else s.TripListSerializer


class TripCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    pagination_class = None
    queryset = m.TripCategory.objects.all()
    lookup_field = 'slug'

    def list(self, request, *a, **k):
        lang = request.query_params.get('lang', 'en')
        return __import__('rest_framework.response', fromlist=['Response']).Response(
            [{'slug': c.slug, 'name': getattr(c, f'name_{lang}', '') or c.name} for c in self.get_queryset()])
