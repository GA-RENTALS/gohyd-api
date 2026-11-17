"""A customer's own privacy rights from their account: download everything we hold, or ask for it to be deleted.

GET  /me/data-export/     the customer's data as a JSON file (recorded as a completed EXPORT request)
GET  /me/data-requests/   their deletion requests and where each one is
POST /me/data-requests/   ask for the account to be deleted; staff process it under All data → Privacy requests,
                          because bookings, invoices and payments must be kept for the period tax law requires.
"""
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import DataRequest
from core.services import audit


def _iso(v):
    return v.isoformat() if v else None


def export_data(user, tenant):
    """Everything this operator holds about the person, in plain fields a person can read."""
    from bookings.models import Booking
    from crm.models import Enquiry, NewsletterSubscription
    from payments.models import Payment
    from trips.models import EventRegistration

    from .models import CustomerProfile
    profile = CustomerProfile.objects.filter(user=user, tenant=tenant).first()
    bookings = Booking.objects.filter(primary_booker=user).select_related('schedule').prefetch_related('participants')
    event_bookings = EventRegistration.objects.filter(registrant=user).select_related('schedule')
    return {
        'exported_at': timezone.now().isoformat(),
        'account': {
            'phone_number': user.phone_number, 'full_name': user.full_name, 'email': user.email,
            'preferred_language': user.preferred_language, 'joined': _iso(user.date_joined),
        },
        'profile': {
            'billing_name': profile.billing_name, 'billing_gstin': profile.billing_gstin, 'billing_address': profile.billing_address,
            'notify_whatsapp': profile.notify_whatsapp, 'notify_email': profile.notify_email, 'marketing_opt_in': profile.marketing_opt_in,
        } if profile else None,
        'trip_bookings': [{
            'reference': b.reference, 'status': b.status, 'starts_at': _iso(b.schedule.starts_at), 'people': b.participant_count,
            'total': str(b.total_amount), 'booked_at': _iso(b.created_at),
            'participants': [{'name': p.full_name, 'age': p.age, 'gender': p.gender, 'phone': p.phone,
                              'emergency_contact': {'name': p.emergency_contact_name, 'phone': p.emergency_contact_phone}}
                             for p in b.participants.all()],
        } for b in bookings],
        'event_bookings': [{
            'reference': r.reference, 'status': r.status, 'starts_at': _iso(r.schedule.starts_at), 'people': r.participant_count,
            'total': str(r.total_amount), 'contact_phone': r.contact_phone, 'booked_at': _iso(r.created_at),
        } for r in event_bookings],
        'payments': [{
            'amount': str(p.amount), 'status': p.status, 'method': p.method, 'kind': p.kind, 'at': _iso(p.created_at),
        } for p in Payment.objects.filter(payer=user)],
        'enquiries': [{'message': e.message, 'status': e.status, 'at': _iso(e.created_at)}
                      for e in Enquiry.objects.filter(phone=user.phone_number)],
        'newsletter': [{'email': n.email, 'subscribed_at': _iso(n.consent_at), 'unsubscribed_at': _iso(n.unsubscribed_at)}
                       for n in NewsletterSubscription.objects.filter(email__iexact=user.email)] if user.email else [],
    }


class DataExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Account'])
    def get(self, request):
        data = export_data(request.user, getattr(request, 'tenant', None))
        with transaction.atomic():
            row = DataRequest.objects.create(user=request.user, kind=DataRequest.Kind.EXPORT,
                                             status=DataRequest.Status.COMPLETED, completed_at=timezone.now(),
                                             note='Downloaded by the customer from their account.')
            audit(request.user, 'privacy.export', row, row.pk, request=request)
        response = JsonResponse(data, json_dumps_params={'indent': 2, 'ensure_ascii': False})
        response['Content-Disposition'] = 'attachment; filename="gohyderabad-my-data.json"'
        return response


class DataRequestView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def _rows(user):
        return [{'id': str(r.pk), 'kind': r.kind, 'status': r.status, 'created_at': _iso(r.created_at),
                 'completed_at': _iso(r.completed_at)}
                for r in DataRequest.objects.filter(user=user, kind=DataRequest.Kind.DELETION).order_by('-created_at')]

    @extend_schema(tags=['Account'])
    def get(self, request):
        return Response({'results': self._rows(request.user)})

    @extend_schema(tags=['Account'])
    def post(self, request):
        """Ask for the account to be deleted. Asking again while one is open changes nothing."""
        open_ = (DataRequest.Status.REQUESTED, DataRequest.Status.IN_PROGRESS)
        with transaction.atomic():
            row = DataRequest.objects.filter(user=request.user, kind=DataRequest.Kind.DELETION, status__in=open_).first()
            created = row is None
            if created:
                row = DataRequest.objects.create(user=request.user, kind=DataRequest.Kind.DELETION,
                                                 note=str(request.data.get('reason', ''))[:1000])
                audit(request.user, 'privacy.deletion_requested', row, row.pk, request=request)
        return Response({'results': self._rows(request.user)}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
