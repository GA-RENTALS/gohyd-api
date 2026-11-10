import uuid

from django.core.exceptions import ValidationError as DjValidationError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.security import get_client_ip
from operations.models import ParticipantWaiverAcceptance, SafetyWaiver
from payments import gateway, services as pay
from payments.models import Refund
from . import models as m
from . import serializers as s
from .services import BookingError, CheckoutLine, cancel_booking, create_checkout


def _active_safety_waiver(waiver_id=None):
    waivers = SafetyWaiver.objects.filter(is_active=True).order_by('-updated_at')
    if waiver_id is not None:
        waivers = waivers.filter(pk=waiver_id)
    return next((waiver for waiver in waivers if waiver.body_en.strip()), None)


def fail(e: BookingError, http=400):
    return Response({'status': 'error', 'code': e.code, 'message': e.message, 'details': e.details}, status=http)


class ActiveSafetyWaiverView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        waiver = _active_safety_waiver()
        if waiver is None:
            return Response(
                {'status': 'error', 'message': 'The participation waiver is not available yet.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        language = request.query_params.get('lang', 'en')
        body = getattr(waiver, f'body_{language}', '') if language in {'en', 'te', 'hi'} else ''
        return Response({
            'id': str(waiver.pk),
            'title': waiver.title,
            'version': waiver.version,
            'language': language if body else 'en',
            'body': body.strip() if body and body.strip() else waiver.body_en.strip(),
        })


class CartView(APIView):
    """Shopping cart with several trips (3.3)."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Cart'], responses=s.CartItemSerializer(many=True))
    def get(self, request):
        cart, _ = m.Cart.objects.get_or_create(user=request.user)
        return Response(s.CartItemSerializer(cart.items.all(), many=True).data)

    @extend_schema(tags=['Cart'], request=s.CartItemSerializer)
    def post(self, request):
        ser = s.CartItemSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        cart, _ = m.Cart.objects.get_or_create(user=request.user)
        item, _ = m.CartItem.objects.update_or_create(cart=cart, schedule=ser.validated_data['schedule'], defaults={
            'participant_count': ser.validated_data['participant_count'], 'pickup_point': ser.validated_data.get('pickup_point')})
        return Response(s.CartItemSerializer(item).data, status=201)

    def delete(self, request):
        m.CartItem.objects.filter(cart__user=request.user, pk=request.query_params.get('item')).delete()
        return Response(status=204)


class CheckoutViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = s.CheckoutSerializer
    pagination_class = None

    def get_queryset(self):
        return m.CheckoutOrder.objects.filter(user=self.request.user).prefetch_related('bookings__schedule__trip__translations', 'bookings__schedule__trip__cover', 'bookings__pickup_point', 'bookings__participants')

    @extend_schema(tags=['Checkout'], request=s.CreateCheckoutSerializer, responses=s.CheckoutSerializer)
    def create(self, request):
        """Create one checkout containing many trips. All-or-nothing: if any trip can't be booked, none are."""
        ser = s.CreateCheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = request.headers.get('Idempotency-Key') or str(uuid.uuid4())
        lines = [CheckoutLine(i['schedule'], i['participant_count'], i.get('pickup_point')) for i in ser.validated_data['items']]
        try:
            order = create_checkout(request.user, lines, key, request)
        except BookingError as e:
            return fail(e, 409 if e.code == 'checkout_unavailable' else 400)
        m.CartItem.objects.filter(cart__user=request.user, schedule_id__in=[l.schedule_id for l in lines]).delete()
        return Response(s.CheckoutSerializer(order).data, status=201)

    @extend_schema(tags=['Payments'], request=s.PayRequestSerializer)
    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        """Create a Razorpay order for the advance (or balance) of some/all bookings in this checkout."""
        order = self.get_object()
        ser = s.PayRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        key = request.headers.get('Idempotency-Key') or str(uuid.uuid4())
        try:
            p = pay.start_online_payment(request.user, order, ser.validated_data['kind'], key, ser.validated_data.get('bookings'))
        except (BookingError, gateway.GatewayError) as e:
            return Response({'status': 'error', 'message': str(e)}, status=400 if isinstance(e, BookingError) else 502)
        return Response({'payment': str(p.pk), 'order_id': p.gateway_order_id, 'amount': p.amount, 'currency': p.currency,
                         'key_id': __import__('django.conf', fromlist=['settings']).settings.RAZORPAY_KEY_ID})

    @extend_schema(tags=['Payments'], request=s.ConfirmPaymentSerializer)
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        self.get_object()
        ser = s.ConfirmPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            p = pay.confirm_from_client(request.user, ser.validated_data['payment'], ser.validated_data['razorpay_payment_id'], ser.validated_data['razorpay_signature'])
        except BookingError as e:
            return fail(e)
        return Response({'status': p.status})


class BookingViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = s.BookingSerializer
    filterset_fields = ['status']

    def get_queryset(self):
        return (m.Booking.objects.filter(primary_booker=self.request.user)
                .select_related('schedule__trip__cover', 'pickup_point').prefetch_related('participants', 'schedule__trip__translations'))

    @extend_schema(tags=['Bookings'], request=s.ParticipantSerializer(many=True))
    @action(detail=True, methods=['put'])
    def participants(self, request, pk=None):
        """The primary booker manages participants (no accounts needed for them). Replaces the list."""
        booking = self.get_object()
        ser = s.ParticipantSerializer(data=request.data, many=True)
        ser.is_valid(raise_exception=True)
        if len(ser.validated_data) > booking.participant_count:
            return Response({'status': 'error', 'message': f'This booking covers {booking.participant_count} participants.'}, status=400)
        booking.participants.all().delete()
        m.BookingParticipant.objects.bulk_create([m.BookingParticipant(booking=booking, **d) for d in ser.validated_data])
        return Response(s.ParticipantSerializer(booking.participants.all(), many=True).data)

    @extend_schema(tags=['Bookings'])
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel this booking only; others in the same checkout are unaffected."""
        booking = self.get_object()
        try:
            booking = cancel_booking(booking, request.user, request.data.get('reason', ''), request)
        except BookingError as e:
            return fail(e)
        return Response(s.BookingSerializer(booking).data)

    @extend_schema(tags=['Bookings'])
    @action(detail=True, methods=['post'], url_path='accept-waiver')
    def accept_waiver(self, request, pk=None):
        booking = self.get_object()
        waiver_id = request.data.get('waiver')
        if not waiver_id:
            return Response({'status': 'error', 'message': 'A waiver version is required.'}, status=status.HTTP_400_BAD_REQUEST)
        waiver = _active_safety_waiver(waiver_id)
        if waiver is None:
            return Response({'status': 'error', 'message': 'This waiver is no longer active. Reload checkout and review the current waiver.'},
                            status=status.HTTP_409_CONFLICT)
        participants = list(booking.participants.all())
        if not participants:
            return Response({'status': 'error', 'message': 'Add the participants before accepting the waiver.'},
                            status=status.HTTP_400_BAD_REQUEST)
        ip = get_client_ip(request)
        for participant in participants:
            ParticipantWaiverAcceptance.objects.get_or_create(
                participant=participant,
                waiver=waiver,
                defaults={'ip': ip},
            )
        booking.participants.update(waiver_accepted_at=timezone.now())
        return Response({'status': 'accepted', 'waiver': str(waiver.pk), 'version': waiver.version})
