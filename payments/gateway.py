"""Thin Razorpay client: orders, signature verification, refunds (extends GoRentals' refund client)."""
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
API_BASE = 'https://api.razorpay.com/v1'
TIMEOUT = 15


class GatewayError(Exception):
    pass


def _auth():
    if not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise GatewayError('Razorpay keys are not configured (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET).')
    return settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET


def _call(method, path, **kw):
    try:
        r = requests.request(method, f'{API_BASE}{path}', auth=_auth(), timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise GatewayError(f"Couldn't reach Razorpay: {exc.__class__.__name__}.") from exc
    if r.status_code not in (200, 201):
        try:
            desc = r.json()['error']['description']
        except (ValueError, KeyError, TypeError):
            desc = f'HTTP {r.status_code}'
        logger.warning('Razorpay %s %s rejected: %s', method, path, desc)
        raise GatewayError(f'Razorpay rejected the request: {desc}')
    return r.json()


def to_minor(amount) -> int:
    """Decimal rupees -> integer paise for the gateway."""
    return int((amount * 100).quantize(1))


def create_order(amount, receipt, notes=None):
    """Orders are always created from the backend (5.2). Returns Razorpay's order dict."""
    return _call('POST', '/orders', json={'amount': to_minor(amount), 'currency': 'INR', 'receipt': receipt[:40], 'notes': notes or {}})


def fetch_payment(payment_id):
    return _call('GET', f'/payments/{payment_id}')


def verify_checkout_signature(order_id, payment_id, signature) -> bool:
    expected = hmac.new(settings.RAZORPAY_KEY_SECRET.encode(), f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or '')


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(settings.RAZORPAY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or '')


def create_refund(razorpay_payment_id, amount, receipt, notes=None):
    return _call('POST', f'/payments/{razorpay_payment_id}/refund',
                 json={'amount': to_minor(amount), 'receipt': receipt[:40], 'notes': notes or {}})['id']
