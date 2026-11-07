import json

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

from core.security import get_client_ip
from . import services


@csrf_exempt
def razorpay_webhook(request):
    """Razorpay webhook: verifies the signature over the raw body, stores the event once, then processes it."""
    if request.method != 'POST':
        return HttpResponse(status=405)
    raw = request.body
    try:
        payload = json.loads(raw)
    except ValueError:
        return HttpResponse(status=400)
    ip = get_client_ip(request)
    event_id = request.headers.get('X-Razorpay-Event-Id') or payload.get('id') or ''
    payload.setdefault('id', event_id)
    try:
        result = services.handle_webhook(raw, request.headers.get('X-Razorpay-Signature', ''), payload, ip)
    except PermissionError:
        return HttpResponse(status=400)
    except Exception:
        return HttpResponse(status=500)   # non-2xx makes Razorpay retry
    return HttpResponse(result)
