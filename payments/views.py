"""Cashfree payment endpoints (all under /api/v1/payments/cashfree/).

    POST create-order/          start paying a trip checkout or an event booking; returns the Cashfree payment_session_id
    GET  verify/<order_id>/     after Cashfree sends the customer back: ask Cashfree, record it, say what happened
    POST webhook/               Cashfree's payment and refund notifications (signature checked over the raw body)

The amount always comes from the booking records on the server, never from the browser.
"""
import json
import uuid

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import CheckoutOrder
from bookings.services import BookingError
from core.security import get_client_ip

from . import gateway, services
from .models import Payment, PaymentKind


class CreateOrderSerializer(serializers.Serializer):
    checkout = serializers.UUIDField(required=False, help_text='A trip checkout: pay its advance or balance.')
    event_booking = serializers.CharField(required=False, max_length=16, help_text='An event booking reference.')
    kind = serializers.ChoiceField(choices=PaymentKind.choices)
    bookings = serializers.ListField(child=serializers.UUIDField(), required=False,
                                     help_text='Trip bookings of the checkout to pay for (default: all).')

    def validate(self, attrs):
        if bool(attrs.get('checkout')) == bool(attrs.get('event_booking')):
            raise serializers.ValidationError('Send either a checkout or an event booking.')
        return attrs


def _session(p: Payment):
    return {'payment': str(p.pk), 'order_id': p.gateway_order_id, 'payment_session_id': p.gateway_session_id,
            'amount': str(p.amount), 'currency': p.currency, 'mode': settings.CASHFREE_ENV}


class CreateOrderView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Payments'], request=CreateOrderSerializer)
    def post(self, request):
        from trips.models import EventRegistration
        data = CreateOrderSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        key = request.headers.get('Idempotency-Key') or str(uuid.uuid4())
        try:
            if v.get('checkout'):
                checkout = CheckoutOrder.objects.filter(pk=v['checkout'], user=request.user).first()
                if checkout is None:
                    return Response({'detail': 'Checkout not found.'}, status=status.HTTP_404_NOT_FOUND)
                p = services.start_online_payment(request.user, checkout, v['kind'], key, v.get('bookings'))
            else:
                reg = EventRegistration.objects.filter(reference=v['event_booking'].strip().upper(), registrant=request.user).first()
                if reg is None:
                    return Response({'detail': 'Booking not found.'}, status=status.HTTP_404_NOT_FOUND)
                p = services.start_event_payment(request.user, reg, v['kind'], key)
        except BookingError as e:
            return Response({'detail': str(e), 'code': e.code}, status=status.HTTP_400_BAD_REQUEST)
        except gateway.GatewayError:
            return Response({'detail': "Online payment isn't available right now. Please try again in a few minutes."},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(_session(p), status=status.HTTP_201_CREATED)


class VerifyView(APIView):
    """The customer is back from Cashfree. Their browser's word is never taken: Cashfree is asked, and only a payment
    of the right amount is recorded. Answers paid | pending | failed | cancelled | expired."""
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Payments'])
    def get(self, request, order_id):
        p = Payment.objects.select_related('event_registration').filter(gateway_order_id=order_id, payer=request.user).first()
        if p is None:
            return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            p, outcome = services.reconcile_order(order_id)
            message = p.failure_reason if outcome != 'paid' else ''
        except gateway.GatewayError:
            outcome, message = 'pending', "We couldn't check with Cashfree yet. Your booking updates as soon as it confirms."
        # Which booking it was for, so the website can show it (or offer to try again) whatever the outcome.
        body = {'status': outcome, 'payment': str(p.pk), 'amount': str(p.amount), 'kind': p.kind, 'message': message}
        if p.checkout_id:
            body['checkout'] = str(p.checkout_id)
        else:
            body['event_booking'] = p.event_registration.reference
        return Response(body)


@csrf_exempt
def cashfree_webhook(request):
    """Cashfree notification: the signature is checked over the raw body, each event is stored once, then processed.
    A non-2xx answer makes Cashfree deliver it again, so only real processing failures return 500."""
    if request.method != 'POST':
        return HttpResponse(status=405)
    raw = request.body
    try:
        payload = json.loads(raw)
    except ValueError:
        return HttpResponse(status=400)
    try:
        result = services.handle_webhook(raw, request.headers.get('x-webhook-timestamp', ''), request.headers.get('x-webhook-signature', ''),
                                         payload, idempotency_key=request.headers.get('x-idempotency-key', ''), ip=get_client_ip(request))
    except PermissionError:
        return HttpResponse(status=400)
    except Exception:   # noqa: BLE001 - stored with its error; Cashfree retries
        return HttpResponse(status=500)
    return HttpResponse(result)
