from django.core.exceptions import ObjectDoesNotExist
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
    name = serializers.CharField(max_length=150, trim_whitespace=True, required=False, allow_blank=True, default='',
                                 help_text="Who the booking is for; defaults to the account's name. The account's phone is used.")
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    participant_count = serializers.IntegerField(min_value=1, max_value=500)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default='')
    coupon = serializers.CharField(max_length=30, required=False, allow_blank=True, default='')
    consent_to_contact = serializers.BooleanField()


class EventCouponPreviewSerializer(serializers.Serializer):
    event = serializers.SlugField()
    participant_count = serializers.IntegerField(min_value=1, max_value=500)
    code = serializers.CharField(max_length=30)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')


class EventBookingCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


# Online refunds as the customer reads them (payments.Refund statuses).
ONLINE_REFUND_LABEL = {'REQUESTED': 'Being reviewed', 'APPROVED': 'Approved', 'PROCESSING': 'On its way to your account',
                       'PROCESSED': 'Refunded', 'FAILED': 'Being retried by our team', 'REJECTED': 'Not refunded'}


def event_refund_info(registration):
    """The refund on a cancelled booking, or None: a Cashfree refund, or (bookings paid by QR before) a UPI refund."""
    online = registration.gateway_refunds.exclude(status='REJECTED').order_by('-created_at').first()
    if online is not None:
        return {'status': online.status, 'status_label': ONLINE_REFUND_LABEL.get(online.status, online.status),
                'amount': str(online.amount), 'upi_reference': '', 'recorded_at': online.updated_at, 'online': True}
    try:
        r = registration.refund
    except ObjectDoesNotExist:
        return None
    return {'status': r.status, 'status_label': r.get_status_display(), 'amount': str(r.amount),
            'upi_reference': r.upi_reference if r.status == r.Status.SENT else '', 'recorded_at': r.recorded_at, 'online': False}


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
    paid = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    pay_now = serializers.SerializerMethodField(help_text='What the customer can pay online now, or null.')
    coupon_code = serializers.SlugRelatedField(source='coupon', slug_field='code', read_only=True)
    cancellation = serializers.SerializerMethodField()
    refund = serializers.SerializerMethodField()

    class Meta:
        model = m.EventRegistration
        fields = ('reference', 'status', 'status_label', 'contact_name', 'participant_count', 'unit_price',
                  'discount_amount', 'coupon_code', 'total_amount', 'reserved_until', 'confirmed_at', 'created_at', 'event_slug', 'event_title',
                  'starts_at', 'ends_at', 'time_tbd', 'venue', 'booking_whatsapp_number', 'seats_left',
                  'advance_amount', 'paid', 'outstanding', 'pay_now', 'cancelled_at', 'cancelled_by_customer',
                  'cancellation', 'refund')

    def get_cancellation(self, o):
        """Whether the customer may cancel now, until when, and what they would get back."""
        if o.effective_status not in (o.Status.PENDING, o.Status.CONFIRMED):
            return None
        bp, amount = o.refund_quote()
        return {'allowed': o.can_customer_cancel(), 'until': o.cancel_deadline(), 'refund_percent': bp / 100,
                'refund_amount': str(amount), 'paid': o.counts_as_paid}

    def get_refund(self, o): return event_refund_info(o)
    def get_paid(self, o): return str(o.paid_online())
    def get_outstanding(self, o): return str(o.outstanding())

    def get_pay_now(self, o):
        """ADVANCE to confirm a booking still held for payment, BALANCE for the rest of a confirmed one, or null."""
        status, paid = o.effective_status, o.paid_online()
        if o.schedule.has_started() or o.total_amount <= 0:
            return None
        if status == o.Status.PENDING and o.advance_amount > paid:
            return {'kind': 'ADVANCE', 'amount': str(o.advance_amount - paid)}
        if status == o.Status.CONFIRMED and o.total_amount > paid and not o._paid_by_qr():
            return {'kind': 'BALANCE', 'amount': str(o.total_amount - paid)}
        return None

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
        fields = ('id', 'slug', 'title', 'summary', 'category', 'category_slug', 'price', 'is_free', 'cover_url', 'next_date',
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
            if not schedule.cancelled_at and (timezone.localtime(schedule.starts_at).date() >= today if schedule.time_tbd
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
    hold_minutes = serializers.SerializerMethodField(help_text='How long a new booking holds its places while it is paid.')
    advance_percent = serializers.SerializerMethodField(help_text='Share of the price paid online when booking (100 = all).')
    cover_alt = serializers.SerializerMethodField()
    cover_credit = serializers.SerializerMethodField()
    cancellation_cutoff_hours = serializers.IntegerField(read_only=True)
    refund_policy = serializers.SerializerMethodField()

    class Meta(EventListSerializer.Meta):
        fields = EventListSerializer.Meta.fields + ('body', 'venue_name', 'venue_address', 'schedules', 'itineraries',
                                                    'things_to_bring', 'inclusions', 'exclusions', 'format_details',
                                                    'rules', 'hold_minutes', 'highlights', 'faqs',
                                                    'headline', 'image_caption', 'format_note', 'schedule_note',
                                                    'seo_title', 'seo_description', 'advance_percent', 'cover_alt',
                                                    'cover_credit', 'cancellation_cutoff_hours', 'refund_policy')

    def get_refund_policy(self, o):
        return [{'hours_before': p.hours_before, 'refund_percent': p.refund_basis_points / 100, 'note': p.note}
                for p in o.refund_policies.all()]

    def get_cover_alt(self, o): return o.cover.alt_text if o.cover_id else ''
    def get_cover_credit(self, o): return o.cover.credit if o.cover_id else ''

    def get_hold_minutes(self, o):
        from bookings.services import checkout_hold_minutes
        return checkout_hold_minutes()

    def get_advance_percent(self, o):
        return 100 if o.advance_basis_points is None else o.advance_basis_points / 100
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
