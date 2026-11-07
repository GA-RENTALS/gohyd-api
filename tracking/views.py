import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from core.throttling import TrustedScopedRateThrottle
from rest_framework.views import APIView

from . import models as m

ALLOWED_EVENTS = [
    'page_view', 'search_performed', 'category_viewed', 'destination_viewed', 'trip_viewed', 'trip_shared', 'trip_saved',
    'registration_started', 'registration_completed', 'booking_started', 'participant_added', 'pickup_selected', 'payment_started',
    'payment_succeeded', 'booking_confirmed', 'booking_cancelled', 'membership_viewed', 'membership_purchased', 'enquiry_submitted',
    'review_submitted',
]
FORBIDDEN_KEYS = {'password', 'otp', 'code', 'card', 'cvv', 'card_number', 'upi', 'token'}   # never stored (9.3)


class EventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=64)
    name = serializers.ChoiceField(choices=ALLOWED_EVENTS)
    path = serializers.CharField(max_length=300, required=False, allow_blank=True)
    properties = serializers.DictField(required=False)
    occurred_at = serializers.DateTimeField(required=False)


class CollectSerializer(serializers.Serializer):
    visitor_id = serializers.UUIDField(required=False)
    session = serializers.DictField(required=False)
    events = EventSerializer(many=True, max_length=50)


def _channel(ref, medium):
    medium = (medium or '').lower()
    if medium in ('cpc', 'paid', 'ppc'): return 'paid'
    if medium == 'email': return 'email'
    if medium in ('social', 'instagram', 'facebook'): return 'social'
    if ref: return 'referral'
    return 'direct'


class CollectView(APIView):
    """
    First-party event ingestion. Respects consent: with no analytics consent only an anonymous visitor row is touched and
    events are dropped. Duplicate (visitor, event_id) deliveries are ignored.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'track'
    authentication_classes = []

    @extend_schema(tags=['Tracking'], request=CollectSerializer)
    def post(self, request):
        s = CollectSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        visitor, _ = m.Visitor.objects.get_or_create(pk=d.get('visitor_id') or uuid.uuid4())
        if visitor.do_not_track or request.headers.get('DNT') == '1':
            return Response({'visitor_id': str(visitor.pk), 'accepted': 0, 'reason': 'do_not_track'})
        consent = visitor.consents.first()
        if not (consent and consent.analytics):
            return Response({'visitor_id': str(visitor.pk), 'accepted': 0, 'reason': 'no_consent'})
        sess = d.get('session') or {}
        session = None
        if sess.get('id'):
            session, _ = m.VisitorSession.objects.get_or_create(pk=sess['id'], defaults=dict(
                visitor=visitor, landing_path=sess.get('landing_path', '')[:300], referrer=sess.get('referrer', '')[:300],
                utm_source=sess.get('utm_source', '')[:80], utm_medium=sess.get('utm_medium', '')[:80], utm_campaign=sess.get('utm_campaign', '')[:120],
                channel=_channel(sess.get('referrer'), sess.get('utm_medium'))))
        accepted = 0
        for e in d['events']:
            props = {k: v for k, v in (e.get('properties') or {}).items() if k.lower() not in FORBIDDEN_KEYS}
            try:
                with transaction.atomic():   # savepoint: a duplicate must not poison an enclosing transaction
                    m.VisitorEvent.objects.create(visitor=visitor, session=session, client_event_id=e['event_id'], name=e['name'],
                                                  path=e.get('path', ''), properties=props, occurred_at=e.get('occurred_at') or timezone.now())
                accepted += 1
            except IntegrityError:
                continue   # duplicate delivery
        return Response({'visitor_id': str(visitor.pk), 'accepted': accepted})


class ConsentSerializer(serializers.Serializer):
    visitor_id = serializers.UUIDField()
    analytics = serializers.BooleanField()
    session_replay = serializers.BooleanField(default=False)
    marketing = serializers.BooleanField(default=False)
    policy_version = serializers.CharField(required=False, allow_blank=True)


class ConsentView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(tags=['Tracking'], request=ConsentSerializer)
    def post(self, request):
        s = ConsentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        visitor, _ = m.Visitor.objects.get_or_create(pk=d['visitor_id'])
        m.TrackingConsent.objects.create(visitor=visitor, analytics=d['analytics'], session_replay=d['session_replay'], marketing=d['marketing'],
                                         policy_version=d.get('policy_version', ''), ip=request.META.get('REMOTE_ADDR'))
        return Response({'status': 'recorded'})
