from rest_framework import serializers

from content.serializers import pick
from . import models as m


class ScheduleSerializer(serializers.ModelSerializer):
    seats_left = serializers.IntegerField(read_only=True)
    advance_basis_points = serializers.SerializerMethodField()
    balance_due_days_before = serializers.SerializerMethodField()

    class Meta:
        model = m.TripSchedule
        fields = ('id', 'starts_at', 'ends_at', 'capacity', 'seats_left', 'price_per_participant', 'currency', 'is_open',
                  'advance_basis_points', 'balance_due_days_before')

    def get_advance_basis_points(self, o):
        from bookings.services import effective_advance_bp
        return effective_advance_bp(o)

    def get_balance_due_days_before(self, o):
        from bookings.services import effective_balance_days
        return effective_balance_days(o)


class PickupSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.TripPickupPoint
        fields = ('id', 'name', 'address', 'pickup_time', 'latitude', 'longitude')


class TripListSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    categories = serializers.SlugRelatedField(many=True, read_only=True, slug_field='slug')
    next_departure = serializers.SerializerMethodField()
    from_price = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    class Meta:
        model = m.Trip
        fields = ('id', 'slug', 'title', 'summary', 'categories', 'operational_status', 'next_departure', 'from_price',
                  'cover_url')

    def _lang(self): return self.context.get('lang', 'en')
    def get_title(self, o): return pick(o, self._lang(), 'title')
    def get_summary(self, o): return pick(o, self._lang(), 'summary')

    def _upcoming(self, o):
        from django.utils import timezone
        return [s for s in o.schedules.all() if s.is_open and s.starts_at > timezone.now()]

    def get_next_departure(self, o):
        up = self._upcoming(o)
        return min((s.starts_at for s in up), default=None)

    def get_from_price(self, o):
        up = self._upcoming(o)
        return min((s.price_per_participant for s in up), default=None)

    def get_cover_url(self, o):
        if not o.cover_id or not o.cover.file:
            return None
        url = o.cover.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class TripDetailSerializer(TripListSerializer):
    body = serializers.SerializerMethodField()
    schedules = serializers.SerializerMethodField()
    pickup_points = PickupSerializer(many=True, read_only=True)
    inclusions = serializers.SerializerMethodField()
    exclusions = serializers.SerializerMethodField()
    policies = serializers.SerializerMethodField()

    class Meta(TripListSerializer.Meta):
        fields = TripListSerializer.Meta.fields + ('body', 'schedules', 'pickup_points', 'inclusions', 'exclusions', 'policies',
                                                    'duration_hours', 'difficulty', 'min_age')

    def get_body(self, o): return pick(o, self._lang(), 'body')

    def get_schedules(self, o):
        return ScheduleSerializer(self._upcoming(o), many=True).data

    def _txt(self, qs):
        lang = self._lang()
        return [getattr(i, f'text_{lang}', '') or i.text_en for i in qs]

    def get_inclusions(self, o): return self._txt(o.inclusions.all())
    def get_exclusions(self, o): return self._txt(o.exclusions.all())
    def get_policies(self, o): return [{'days_before': p.days_before, 'refund_basis_points': p.refund_basis_points, 'note': p.note} for p in o.policies.all()]
