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
    seo_title = serializers.SerializerMethodField()
    seo_description = serializers.SerializerMethodField()

    class Meta(TripListSerializer.Meta):
        fields = TripListSerializer.Meta.fields + ('body', 'schedules', 'pickup_points', 'inclusions', 'exclusions', 'policies',
                                                    'itineraries', 'things_to_bring',
                                                    'duration_hours', 'difficulty', 'min_age', 'seo_title', 'seo_description')

    def get_body(self, o): return pick(o, self._lang(), 'body')
    def get_seo_title(self, o): return pick(o, self._lang(), 'seo_title')
    def get_seo_description(self, o): return pick(o, self._lang(), 'seo_description')

    def get_schedules(self, o):
        return ScheduleSerializer(self._upcoming(o), many=True).data

    def _txt(self, qs):
        lang = self._lang()
        return [getattr(i, f'text_{lang}', '') or i.text_en for i in qs]

    def get_inclusions(self, o): return self._txt(o.inclusions.all())
    def get_exclusions(self, o): return self._txt(o.exclusions.all())
    def get_things_to_bring(self, o): return self._txt(o.things_to_bring.all())

    def get_policies(self, o):
        return [{'days_before': p.days_before, 'refund_basis_points': p.refund_basis_points, 'note': p.note}
                for p in o.policies.all()]


class EventBookingCreateSerializer(serializers.Serializer):
    event = serializers.SlugField()
    schedule = serializers.UUIDField()
    name = serializers.CharField(max_length=150, trim_whitespace=True)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    participant_count = serializers.IntegerField(min_value=1, max_value=500)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default='')
    consent_to_contact = serializers.BooleanField()

    def validate_phone(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from accounts.models import normalize_phone
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)

    def validate_consent_to_contact(self, value):
        if not value:
            raise serializers.ValidationError('Please allow us to contact you to confirm the booking.')
        return value


class EventPaymentProofSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    screenshot = serializers.FileField()
    utr = serializers.CharField(max_length=40, required=False, allow_blank=True, default='')

    def validate_phone(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError
        from accounts.models import normalize_phone
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)


def _media_url(asset, request=None):
    if not asset or not asset.file:
        return None
    try:
        url = asset.file.url
    except (ValueError, OSError):
        return None
    return request.build_absolute_uri(url) if request and url.startswith('/') else url


def event_payment_info(event, request=None):
    """UPI QR details shown to customers, or None when the event doesn't take QR payments."""
    url = _media_url(event.payment_qr, request) if event.payment_qr_id else None
    if not url and not event.payment_upi_id:
        return None
    # qr_url may be null (UPI ID only, no image uploaded yet): the website then uses its bundled QR, if it has one.
    return {'qr_url': url, 'upi_id': event.payment_upi_id, 'payee_name': event.payment_payee_name}


class EventBookingSerializer(serializers.ModelSerializer):
    """What the visitor sees about their own booking. Pending holds are never reported as confirmed."""
    status = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    event_slug = serializers.CharField(source='schedule.event.slug')
    event_title = serializers.SerializerMethodField()
    starts_at = serializers.DateTimeField(source='schedule.starts_at')
    ends_at = serializers.DateTimeField(source='schedule.ends_at')
    time_tbd = serializers.BooleanField(source='schedule.time_tbd')
    venue = serializers.SerializerMethodField()
    booking_whatsapp_number = serializers.CharField(source='schedule.event.booking_whatsapp_number')
    seats_left = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    payment_submitted = serializers.SerializerMethodField()

    class Meta:
        model = m.EventRegistration
        fields = ('reference', 'status', 'status_label', 'contact_name', 'participant_count', 'unit_price',
                  'total_amount', 'reserved_until', 'confirmed_at', 'created_at', 'event_slug', 'event_title',
                  'starts_at', 'ends_at', 'time_tbd', 'venue', 'booking_whatsapp_number', 'seats_left',
                  'payment', 'payment_submitted', 'payment_submitted_at')

    def get_payment(self, o): return event_payment_info(o.schedule.event, self.context.get('request'))
    def get_payment_submitted(self, o): return bool(o.payment_screenshot)

    def get_status(self, o): return o.effective_status
    def get_status_label(self, o): return m.EventRegistration.Status(o.effective_status).label
    def get_event_title(self, o): return pick(o.schedule.event, self.context.get('lang', 'en'), 'title')
    def get_venue(self, o): return o.schedule.event.venue_address or o.schedule.event.venue_name
    def get_seats_left(self, o): return o.schedule.seats_left()


class EventScheduleSerializer(serializers.ModelSerializer):
    seats_left = serializers.SerializerMethodField()

    class Meta:
        model = m.EventSchedule
        fields = ('id', 'starts_at', 'ends_at', 'capacity', 'seats_left', 'is_date_locked', 'time_tbd')

    def get_seats_left(self, o):
        return o.seats_left()


class EventItineraryItemSerializer(serializers.ModelSerializer):
    text = serializers.SerializerMethodField()
    detail = serializers.SerializerMethodField()

    class Meta:
        model = m.EventItineraryItem
        fields = ('id', 'time_label', 'text', 'detail')

    def get_text(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'text_{lang}', '') or o.text_en

    def get_detail(self, o):
        lang = self.context.get('lang', 'en')
        return getattr(o, f'detail_{lang}', '') or o.detail_en


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
    next_seats_left = serializers.SerializerMethodField()
    popup_banner_url = serializers.SerializerMethodField()

    class Meta:
        model = m.Event
        fields = ('id', 'slug', 'title', 'summary', 'category', 'category_slug', 'price', 'cover_url', 'next_date',
                  'next_time_tbd', 'is_featured', 'booking_whatsapp_number', 'show_in_popup', 'popup_order',
                  'popup_banner_url', 'next_seats_left', 'registration_type', 'max_participants_per_booking')

    def _lang(self): return self.context.get('lang', 'en')
    def get_title(self, o): return pick(o, self._lang(), 'title')
    def get_summary(self, o): return pick(o, self._lang(), 'summary')
    def get_category(self, o):
        return (getattr(o.category, f'name_{self._lang()}', '') or o.category.name) if o.category_id else ''

    def _asset_url(self, asset):
        if asset is None or not asset.file:
            return None
        url = asset.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def get_cover_url(self, o):
        return self._asset_url(o.cover) if o.cover_id else None

    def get_popup_banner_url(self, o):
        return self._asset_url(o.popup_banner) if o.popup_banner_id else None

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

    def get_next_seats_left(self, o):
        schedule = self._next_schedule(o)
        return schedule.seats_left() if schedule else None

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
    format_details = serializers.SerializerMethodField()
    rules = serializers.SerializerMethodField()
    highlights = serializers.SerializerMethodField()
    faqs = serializers.SerializerMethodField()
    headline = serializers.SerializerMethodField()
    image_caption = serializers.SerializerMethodField()
    format_note = serializers.SerializerMethodField()
    schedule_note = serializers.SerializerMethodField()
    seo_title = serializers.SerializerMethodField()
    seo_description = serializers.SerializerMethodField()
    reservation_hold_hours = serializers.IntegerField(read_only=True)
    payment = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + ('body', 'venue_name', 'venue_address', 'schedules', 'itineraries',
                                                    'things_to_bring', 'inclusions', 'exclusions', 'format_details',
                                                    'rules', 'reservation_hold_hours', 'highlights', 'faqs',
                                                    'headline', 'image_caption', 'format_note', 'schedule_note',
                                                    'seo_title', 'seo_description', 'payment')

    def get_payment(self, o): return event_payment_info(o, self.context.get('request'))
    def get_body(self, o): return pick(o, self._lang(), 'body')
    def get_schedules(self, o): return EventScheduleSerializer(self._upcoming(o), many=True).data

    def _txt(self, qs):
        lang = self._lang()
        return [getattr(item, f'text_{lang}', '') or item.text_en for item in qs]

    def get_things_to_bring(self, o): return self._txt(o.things_to_bring.all())
    def get_inclusions(self, o): return self._txt(o.inclusions.all())
    def get_exclusions(self, o): return self._txt(o.exclusions.all())
    def get_rules(self, o): return self._txt(o.rules.all())
    def get_highlights(self, o): return self._txt(o.highlights.all())
    def get_headline(self, o): return pick(o, self._lang(), 'headline')
    def get_image_caption(self, o): return pick(o, self._lang(), 'image_caption')
    def get_format_note(self, o): return pick(o, self._lang(), 'format_note')
    def get_schedule_note(self, o): return pick(o, self._lang(), 'schedule_note')
    def get_seo_title(self, o): return pick(o, self._lang(), 'seo_title')
    def get_seo_description(self, o): return pick(o, self._lang(), 'seo_description')

    def get_faqs(self, o):
        lang = self._lang()
        return [{'question': getattr(f, f'question_{lang}', '') or f.question_en,
                 'answer': getattr(f, f'answer_{lang}', '') or f.answer_en} for f in o.faqs.all()]

    def get_format_details(self, o):
        lang = self._lang()
        return [{'label': getattr(d, f'label_{lang}', '') or d.label_en, 'value': getattr(d, f'value_{lang}', '') or d.value_en}
                for d in o.format_details.all()]
