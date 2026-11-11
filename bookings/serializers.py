from rest_framework import serializers

from payments.models import Payment
from . import models as m
from .services import can_depart, outstanding, paid_amount


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = m.BookingParticipant
        fields = ('id', 'full_name', 'age', 'gender', 'phone', 'emergency_contact_name', 'emergency_contact_phone', 'medical_notes', 'waiver_accepted_at')
        read_only_fields = ('id', 'waiver_accepted_at')


class BookingSerializer(serializers.ModelSerializer):
    trip = serializers.CharField(source='schedule.trip.slug', read_only=True)
    trip_title = serializers.SerializerMethodField()
    trip_cover = serializers.SerializerMethodField()
    pickup_point_name = serializers.SerializerMethodField()
    starts_at = serializers.DateTimeField(source='schedule.starts_at', read_only=True)
    paid = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    participants = ParticipantSerializer(many=True, read_only=True)
    invoice_number = serializers.SerializerMethodField()

    class Meta:
        model = m.Booking
        fields = ('id', 'reference', 'status', 'checkout', 'trip', 'trip_title', 'trip_cover', 'pickup_point_name', 'created_at', 'starts_at', 'participant_count', 'currency', 'discount_amount', 'subtotal', 'tax_amount', 'total_amount', 'invoice_number',
                  'advance_basis_points', 'advance_amount', 'balance_amount', 'balance_due_at', 'paid', 'outstanding', 'is_overdue', 'participants')

    def get_trip_title(self, o):
        """A customer who booked a trip should always see its name, even if the translation is not published any more."""
        rows = {t.language: t for t in o.schedule.trip.translations.all()}
        row = rows.get('en') or next(iter(rows.values()), None)
        return row.title if row and row.title else o.schedule.trip.slug

    def get_trip_cover(self, o):
        cover = o.schedule.trip.cover
        if not cover or not cover.file:
            return None
        url = cover.file.url
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def get_pickup_point_name(self, o):
        return o.pickup_point.name if o.pickup_point_id else ''

    def get_invoice_number(self, o):
        inv = o.invoices.first()
        return inv.number if inv else None

    def get_paid(self, o): return paid_amount(o)
    def get_outstanding(self, o): return outstanding(o)

    def get_is_overdue(self, o):
        from django.utils import timezone
        return o.status not in ('FULLY_PAID', 'CANCELLED', 'COMPLETED') and outstanding(o) > 0 and o.balance_due_at < timezone.now()


class CheckoutLineSerializer(serializers.Serializer):
    schedule = serializers.UUIDField()
    participant_count = serializers.IntegerField(min_value=1, max_value=50)
    pickup_point = serializers.UUIDField(required=False, allow_null=True)


class CreateCheckoutSerializer(serializers.Serializer):
    items = CheckoutLineSerializer(many=True, allow_empty=False)
    coupon = serializers.CharField(required=False, allow_blank=True, max_length=30)


class CouponPreviewSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    items = CheckoutLineSerializer(many=True, allow_empty=False)


class CheckoutSerializer(serializers.ModelSerializer):
    bookings = BookingSerializer(many=True, read_only=True)

    class Meta:
        model = m.CheckoutOrder
        fields = ('id', 'reference', 'status', 'currency', 'coupon_code', 'discount_total', 'total_amount', 'advance_total', 'created_at', 'bookings')

    coupon_code = serializers.CharField(source='coupon.code', default=None, read_only=True)


class PayRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['ADVANCE', 'BALANCE', 'FULL'])
    bookings = serializers.ListField(child=serializers.UUIDField(), required=False)


class ConfirmPaymentSerializer(serializers.Serializer):
    payment = serializers.UUIDField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class CartItemSerializer(serializers.ModelSerializer):
    """Write: schedule, participant_count, pickup_point. Read: also what the cart page needs to show each line."""
    trip = serializers.CharField(source='schedule.trip.slug', read_only=True)
    trip_title = serializers.SerializerMethodField()
    starts_at = serializers.DateTimeField(source='schedule.starts_at', read_only=True)
    ends_at = serializers.DateTimeField(source='schedule.ends_at', read_only=True)
    price_per_participant = serializers.DecimalField(source='schedule.price_per_participant', max_digits=12, decimal_places=2, read_only=True)
    seats_left = serializers.IntegerField(source='schedule.seats_left', read_only=True)
    is_bookable = serializers.SerializerMethodField()
    pickup_point_name = serializers.SerializerMethodField()

    class Meta:
        model = m.CartItem
        fields = ('id', 'schedule', 'participant_count', 'pickup_point', 'trip', 'trip_title', 'starts_at', 'ends_at',
                  'price_per_participant', 'seats_left', 'is_bookable', 'pickup_point_name')

    def get_trip_title(self, o):
        from content.serializers import pick
        return pick(o.schedule.trip, self.context.get('lang', 'en'), 'title') or o.schedule.trip.slug

    def get_is_bookable(self, o):
        from django.utils import timezone
        s = o.schedule
        return (s.is_open and s.trip.status == 'PUBLISHED' and s.trip.operational_status == 'OPEN'
                and s.starts_at > timezone.now() and s.seats_left >= o.participant_count)

    def get_pickup_point_name(self, o):
        return o.pickup_point.name if o.pickup_point_id else ''


class InvoiceItemSerializer(serializers.Serializer):
    description = serializers.CharField()
    quantity = serializers.IntegerField()
    unit_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)


class InvoiceSerializer(serializers.Serializer):
    """A customer's GST invoice, exactly as issued (snapshot values, never live settings)."""
    number = serializers.CharField()
    issued_at = serializers.DateTimeField()
    currency = serializers.CharField()
    seller = serializers.JSONField(source='entity_snapshot')
    billing_name = serializers.CharField()
    billing_gstin = serializers.CharField()
    billing_address = serializers.CharField()
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax = serializers.JSONField(source='tax_snapshot')
    booking_reference = serializers.CharField(source='booking.reference')
    discount_amount = serializers.DecimalField(source='booking.discount_amount', max_digits=12, decimal_places=2)
    items = InvoiceItemSerializer(many=True)
