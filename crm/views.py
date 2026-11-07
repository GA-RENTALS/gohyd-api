from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers
from rest_framework.response import Response
from core.throttling import TrustedScopedRateThrottle
from rest_framework.views import APIView

from . import models as m


class EnquirySerializer(serializers.ModelSerializer):
    source = serializers.CharField(required=False, default='website')
    trip = serializers.SlugRelatedField(slug_field='slug', queryset=__import__('trips.models', fromlist=['Trip']).Trip.objects.all(), required=False, allow_null=True)

    class Meta:
        model = m.Enquiry
        fields = ('name', 'phone', 'email', 'message', 'trip', 'source', 'consent_to_contact')

    def validate(self, a):
        if not (a.get('phone') or a.get('email')):
            raise serializers.ValidationError('Provide a phone number or an email so we can reply.')
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
