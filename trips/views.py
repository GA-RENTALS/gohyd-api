from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from django.db.models import Q
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.throttling import TrustedScopedRateThrottle

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
                .prefetch_related('translations', 'schedules', 'categories', 'pickup_points', 'inclusions', 'exclusions',
                                  'policies', 'itineraries__items', 'things_to_bring').distinct())

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


class EventViewSet(LangMixin, viewsets.ReadOnlyModelViewSet):
    """Published public event details; slot confirmation is handled through CRM enquiries for now."""
    filterset_fields = ['category__slug', 'show_in_popup', 'is_featured']
    search_fields = ['slug', 'translations__title']
    queryset = (m.Event.objects.filter(status=ContentStatus.PUBLISHED)
                .select_related('cover', 'popup_banner', 'category', 'payment_qr')
                .prefetch_related('translations', 'schedules', 'itineraries__items', 'things_to_bring',
                                  'inclusions', 'exclusions', 'format_details', 'rules', 'highlights',
                                  'faqs').distinct())

    def get_serializer_class(self):
        return s.EventDetailSerializer if self.action == 'retrieve' else s.EventListSerializer


class EventBookingCreateView(APIView):
    """Holds slots for an individual or group on a published event date. Staff confirm the booking afterwards."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'

    @extend_schema(tags=['Events'], request=s.EventBookingCreateSerializer, responses=s.EventBookingSerializer)
    def post(self, request):
        from .event_booking import create_event_booking
        data = s.EventBookingCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            booking = create_event_booking(
                event_slug=v['event'], schedule_id=v['schedule'], name=v['name'], phone=v['phone'], email=v.get('email', ''),
                participant_count=v['participant_count'], note=v.get('note', ''))
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'error_dict') else {'detail': exc.messages}
            return Response(detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(s.EventBookingSerializer(booking, context={'request': request, 'lang': request.query_params.get('lang', 'en')}).data,
                        status=status.HTTP_201_CREATED)


class EventBookingStatusView(APIView):
    """Look up one booking by reference. The phone used to book must match, so references cannot be enumerated."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'

    @extend_schema(tags=['Events'], responses=s.EventBookingSerializer)
    def get(self, request, reference):
        from accounts.models import normalize_phone
        not_found = Response({'detail': 'No booking matches that reference and phone number.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            phone = normalize_phone(request.query_params.get('phone', ''))
        except DjangoValidationError:
            return not_found
        booking = (m.EventRegistration.objects.select_related('schedule__event')
                   .filter(reference=reference.strip().upper(), contact_phone=phone).first())
        if booking is None:
            return not_found
        return Response(s.EventBookingSerializer(booking, context={'request': request, 'lang': request.query_params.get('lang', 'en')}).data)


class EventPaymentProofView(APIView):
    """The customer uploads their UPI payment screenshot. Reference + booking phone must match."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(tags=['Events'], request={'multipart/form-data': s.EventPaymentProofSerializer}, responses=s.EventBookingSerializer)
    def post(self, request, reference):
        from .event_booking import PaymentStorageError, submit_payment_proof
        data = s.EventPaymentProofSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            booking = submit_payment_proof(reference=reference, phone=v['phone'], screenshot=v['screenshot'], utr=v.get('utr', ''))
        except PaymentStorageError:
            return Response({'detail': "We couldn't save your screenshot right now. Please try again in a few minutes, "
                                       'or send it to us on WhatsApp with your booking reference.'},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, 'error_dict') else {'detail': exc.messages}
            code = status.HTTP_404_NOT_FOUND if 'No booking matches' in str(detail) else status.HTTP_400_BAD_REQUEST
            if isinstance(detail.get('detail'), list):
                detail['detail'] = detail['detail'][0]
            return Response(detail, status=code)
        return Response(s.EventBookingSerializer(booking, context={'request': request, 'lang': request.query_params.get('lang', 'en')}).data)


class MyEventBookingsView(APIView):
    """The signed-in customer's event bookings. Public event booking needs no login, so bookings made with the
    account's (OTP-verified) phone number count too, not only ones linked through `registrant`."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=['Events'], responses=s.EventBookingSerializer(many=True))
    def get(self, request):
        user = request.user
        bookings = (m.EventRegistration.objects.select_related('schedule__event')
                    .filter(Q(registrant=user) | Q(contact_phone=user.phone_number))
                    .order_by('-created_at'))
        return Response(s.EventBookingSerializer(bookings, many=True, context={'request': request, 'lang': request.query_params.get('lang', 'en')}).data)
