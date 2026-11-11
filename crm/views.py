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
