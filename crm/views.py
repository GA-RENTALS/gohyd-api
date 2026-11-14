from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from core.throttling import TrustedScopedRateThrottle
from rest_framework.views import APIView
from django.utils import timezone

from content.models import ContentStatus
from . import models as m


class EnquirySerializer(serializers.ModelSerializer):
    source = serializers.CharField(required=False, default='website')
    trip = serializers.SlugRelatedField(slug_field='slug', queryset=__import__('trips.models', fromlist=['Trip']).Trip.objects.all(), required=False, allow_null=True)
    event = serializers.SlugRelatedField(slug_field='slug', queryset=__import__('trips.models', fromlist=['Event']).Event.objects.filter(status=ContentStatus.PUBLISHED), required=False, allow_null=True)
    event_schedule = serializers.PrimaryKeyRelatedField(queryset=__import__('trips.models', fromlist=['EventSchedule']).EventSchedule.objects.all(), required=False, allow_null=True)

    class Meta:
        model = m.Enquiry
        fields = ('name', 'phone', 'email', 'message', 'trip', 'event', 'event_schedule', 'preferred_date',
                  'group_size', 'source', 'consent_to_contact')

    def validate(self, a):
        if not (a.get('phone') or a.get('email')):
            raise serializers.ValidationError('Provide a phone number or an email so we can reply.')
        schedule = a.get('event_schedule')
        event = a.get('event')
        if schedule and (event is None or schedule.event_id != event.pk):
            raise serializers.ValidationError({'event_schedule': 'Choose a date belonging to the selected event.'})
        schedule_is_past = schedule and (
            timezone.localtime(schedule.starts_at).date() < timezone.localdate()
            if schedule.time_tbd else schedule.starts_at <= timezone.now()
        )
        if schedule_is_past:
            raise serializers.ValidationError({'event_schedule': 'Choose a future event date.'})
        if schedule and schedule.capacity and a.get('group_size') and a['group_size'] > schedule.capacity:
            raise serializers.ValidationError({'group_size': f'This event accepts at most {schedule.capacity} people per request.'})
        if a.get('preferred_date') and a['preferred_date'] < timezone.localdate():
            raise serializers.ValidationError({'preferred_date': 'Choose today or a future date.'})
        if schedule and a.get('preferred_date'):
            raise serializers.ValidationError('Choose either a published event date or a preferred date, not both.')
        return a

    def create(self, v):
        src, _ = m.EnquirySource.objects.get_or_create(name=v.pop('source', 'website'))
        return m.Enquiry.objects.create(source=src, **v)


class CorporateEnquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = m.CorporateEnquiry
        fields = ('company', 'contact_name', 'phone', 'email', 'group_size', 'preferred_dates', 'brief')


class EnquiryView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'

    @extend_schema(tags=['CRM'], request=EnquirySerializer)
    def post(self, request):
        s = EnquirySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({'status': 'received'}, status=201)


class CorporateEnquiryView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'

    @extend_schema(tags=['CRM'], request=CorporateEnquirySerializer)
    def post(self, request):
        s = CorporateEnquirySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({'status': 'received'}, status=201)


# ---------- newsletter ----------

class NewsletterSubscribeSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    consent = serializers.BooleanField()

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError('Please agree to receive our emails.')
        return value


class NewsletterSubscribeView(APIView):
    """Footer sign-up. Signing up again with an address that had unsubscribed subscribes it again."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [TrustedScopedRateThrottle]
    throttle_scope = 'enquiry'

    @extend_schema(tags=['CRM'], request=NewsletterSubscribeSerializer)
    def post(self, request):
        data = NewsletterSubscribeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data['email'].strip().lower()
        subscription = m.NewsletterSubscription.objects.filter(email__iexact=email).first()
        if subscription is None:
            m.NewsletterSubscription.objects.create(email=email, consent_at=timezone.now())
        elif subscription.unsubscribed_at:
            subscription.unsubscribed_at, subscription.consent_at = None, timezone.now()
            subscription.save(update_fields=['unsubscribed_at', 'consent_at', 'updated_at'])
        # Same answer whether or not the address was already on the list, so the form can't be used to look people up.
        return Response({'status': 'subscribed'}, status=201)


# ---------- membership plans ----------

class MembershipPlanSerializer(serializers.ModelSerializer):
    discount_percent = serializers.SerializerMethodField()
    benefits = serializers.SerializerMethodField()

    class Meta:
        model = m.MembershipPlan
        fields = ('id', 'name', 'price', 'duration_days', 'discount_percent', 'benefits')

    def get_discount_percent(self, plan):
        return plan.discount_basis_points / 100

    def get_benefits(self, plan):
        return [b.text for b in plan.benefits.all()]


class MembershipPlanListView(APIView):
    """Active membership plans for the /membership page, cheapest first."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(tags=['CRM'], responses=MembershipPlanSerializer(many=True))
    def get(self, request):
        plans = m.MembershipPlan.objects.filter(is_active=True).prefetch_related('benefits').order_by('price', 'name')
        return Response(MembershipPlanSerializer(plans, many=True).data)
