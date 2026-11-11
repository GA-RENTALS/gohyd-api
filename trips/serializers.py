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


class ItineraryItemSerializer(serializers.ModelSerializer):
    text = serializers.SerializerMethodField()

    class Meta:
        model = m.TripItineraryItem
        fields = ('id', 'time_label', 'text')

    def get_text(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'text_{lang}', '') or o.text_en


class ItinerarySerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    items = ItineraryItemSerializer(many=True, read_only=True)

    class Meta:
        model = m.TripItinerary
        fields = ('id', 'day_number', 'title', 'items')

    def get_title(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'title_{lang}', '') or o.title_en


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
        if o.operational_status != m.Trip.Operational.OPEN:
            return []
        return [s for s in o.schedules.all() if s.is_open and s.seats_left > 0 and s.starts_at > timezone.now()]

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
    itineraries = ItinerarySerializer(many=True, read_only=True)
    things_to_bring = serializers.SerializerMethodField()

    class Meta(TripListSerializer.Meta):
        fields = TripListSerializer.Meta.fields + ('body', 'schedules', 'pickup_points', 'inclusions', 'exclusions', 'policies',
                                                    'itineraries', 'things_to_bring',
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
    def get_things_to_bring(self, o):
        lang = self.context.get('lang', 'en')
        return [getattr(item, f'text_{lang}', '') or item.text_en for item in o.things_to_bring.all()]


class EventScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.EventSchedule
        fields = ('id', 'starts_at', 'ends_at', 'capacity', 'is_date_locked', 'time_tbd')


class EventItineraryItemSerializer(serializers.ModelSerializer):
    text = serializers.SerializerMethodField()

    class Meta:
        model = m.EventItineraryItem
        fields = ('id', 'time_label', 'text')

    def get_text(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'text_{lang}', '') or o.text_en


class EventItinerarySerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    items = EventItineraryItemSerializer(many=True, read_only=True)

    class Meta:
        model = m.EventItinerary
        fields = ('id', 'day_number', 'title', 'items')

    def get_title(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'title_{lang}', '') or o.title_en


class EventListSerializer(serializers.ModelSerializer):
    title = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    category_slug = serializers.SlugRelatedField(source='category', slug_field='slug', read_only=True)
    cover_url = serializers.SerializerMethodField()
    next_date = serializers.SerializerMethodField()
    next_time_tbd = serializers.SerializerMethodField()

    class Meta:
        model = m.Event
        fields = ('id', 'slug', 'title', 'summary', 'category', 'category_slug', 'price', 'cover_url', 'next_date',
                  'next_time_tbd', 'is_featured', 'booking_whatsapp_number')

    def _lang(self): return self.context.get('lang', 'en')
    def get_title(self, o): return pick(o, self._lang(), 'title')
    def get_summary(self, o): return pick(o, self._lang(), 'summary')
    def get_category(self, o):
        return (getattr(o.category, f'name_{self._lang()}', '') or o.category.name) if o.category_id else ''

    def get_cover_url(self, o):
        if not o.cover_id or not o.cover.file:
            return None
        url = o.cover.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def _upcoming(self, o):
        from django.utils import timezone
        today = timezone.localdate()
        return [
            schedule for schedule in o.schedules.all()
            if (timezone.localtime(schedule.starts_at).date() >= today if schedule.time_tbd
                else schedule.starts_at > timezone.now())
        ]

    def get_next_date(self, o):
        schedule = self._next_schedule(o)
        return schedule.starts_at if schedule else None

    def _next_schedule(self, o):
        return min(self._upcoming(o), key=lambda schedule: schedule.starts_at, default=None)

    def get_next_time_tbd(self, o):
        schedule = self._next_schedule(o)
        return schedule.time_tbd if schedule else False


class EventDetailSerializer(EventListSerializer):
    body = serializers.SerializerMethodField()
    schedules = serializers.SerializerMethodField()
    itineraries = EventItinerarySerializer(many=True, read_only=True)
    venue_name = serializers.CharField(read_only=True)
    venue_address = serializers.CharField(read_only=True)
    booking_whatsapp_number = serializers.CharField(read_only=True)
    things_to_bring = serializers.SerializerMethodField()
    inclusions = serializers.SerializerMethodField()
    exclusions = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + ('body', 'venue_name', 'venue_address', 'schedules', 'itineraries',
                                                    'things_to_bring', 'inclusions', 'exclusions')

    def get_body(self, o): return pick(o, self._lang(), 'body')
    def get_schedules(self, o): return EventScheduleSerializer(self._upcoming(o), many=True).data

    def _txt(self, qs):
        lang = self._lang()
        return [getattr(item, f'text_{lang}', '') or item.text_en for item in qs]

    def get_things_to_bring(self, o): return self._txt(o.things_to_bring.all())
    def get_inclusions(self, o): return self._txt(o.inclusions.all())
    def get_exclusions(self, o): return self._txt(o.exclusions.all())
