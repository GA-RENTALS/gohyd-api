"""Thin Cashfree Payment Gateway client: orders, payment lookups, refunds and webhook signatures.

The API is called only from the backend with the App ID and Secret Key (settings.CASHFREE_*); the browser only ever
receives an order's `payment_session_id`. Nothing here decides whether a booking is paid: payments.services asks
Cashfree for an order's payments and records only a SUCCESS for the right amount and currency.

API reference: https://www.cashfree.com/docs/api-reference/payments/latest/
"""
import base64
import hashlib
import hmac
import logging
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
API_BASE = {'sandbox': 'https://sandbox.cashfree.com/pg', 'production': 'https://api.cashfree.com/pg'}
TIMEOUT = 15


class GatewayError(Exception):
    pass


def configured() -> bool:
    return bool(settings.CASHFREE_APP_ID and settings.CASHFREE_SECRET_KEY)


def _headers(idempotency_key=None):
    if not configured():
        raise GatewayError('Cashfree is not configured (CASHFREE_APP_ID, CASHFREE_SECRET_KEY).')
    headers = {
        'x-client-id': settings.CASHFREE_APP_ID,
        'x-client-secret': settings.CASHFREE_SECRET_KEY,
        'x-api-version': settings.CASHFREE_API_VERSION,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if idempotency_key:
        headers['x-idempotency-key'] = idempotency_key
    return headers


def _call(method, path, idempotency_key=None, **kw):
    url = f'{API_BASE[settings.CASHFREE_ENV]}{path}'
    try:
        r = requests.request(method, url, headers=_headers(idempotency_key), timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise GatewayError(f"Couldn't reach Cashfree: {exc.__class__.__name__}.") from exc
    if r.status_code not in (200, 201):
        try:
            desc = r.json().get('message') or f'HTTP {r.status_code}'
        except ValueError:
            desc = f'HTTP {r.status_code}'
        logger.warning('Cashfree %s %s rejected (%s): %s', method, path, r.status_code, desc)   # never log the headers
        raise GatewayError(f'Cashfree rejected the request: {desc}')
    return r.json()


def amount(value) -> float:
    """Decimal rupees -> the number Cashfree expects (rupees, two decimals)."""
    return float(Decimal(value).quantize(Decimal('0.01')))


def customer_phone(phone_number: str) -> str:
    """Cashfree wants a 10-digit Indian number; other countries keep their + prefix."""
    digits = ''.join(ch for ch in phone_number if ch.isdigit())
    return digits[-10:] if phone_number.startswith('+91') or len(digits) == 10 else phone_number


def create_order(*, order_id, order_amount, customer, return_url, notify_url, tags, note):
    """Create an order; returns Cashfree's order (with `payment_session_id`). `order_id` doubles as idempotency key."""
    body = {
        'order_id': order_id,
        'order_amount': amount(order_amount),
        'order_currency': 'INR',
        'customer_details': customer,
        'order_meta': {'return_url': return_url, **({'notify_url': notify_url} if notify_url else {})},
        'order_tags': {k: str(v)[:255] for k, v in tags.items() if v not in (None, '')},
        'order_note': note[:200],
    }
    return _call('POST', '/orders', idempotency_key=order_id, json=body)


def get_order(order_id):
    return _call('GET', f'/orders/{order_id}')


def get_order_payments(order_id) -> list:
    return _call('GET', f'/orders/{order_id}/payments')


def create_refund(*, order_id, refund_id, refund_amount, note):
    """Refund part or all of an order's payment. `refund_id` is ours and unique, so a retry can't refund twice."""
    return _call('POST', f'/orders/{order_id}/refunds', idempotency_key=refund_id,
                 json={'refund_amount': amount(refund_amount), 'refund_id': refund_id, 'refund_note': note[:100] or 'Refund'})


def get_refund(order_id, refund_id):
    return _call('GET', f'/orders/{order_id}/refunds/{refund_id}')


def verify_webhook_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """Cashfree signs base64(HMAC-SHA256(timestamp + raw body, secret key)). The raw body must not be re-serialised."""
    if not (settings.CASHFREE_SECRET_KEY and timestamp and signature):
        return False
    message = timestamp.encode() + raw_body
    expected = base64.b64encode(hmac.new(settings.CASHFREE_SECRET_KEY.encode(), message, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature)


def sign_webhook(raw_body: bytes, timestamp: str) -> str:
    """The signature Cashfree would send: for tests and for checking a captured payload by hand."""
    return base64.b64encode(hmac.new(settings.CASHFREE_SECRET_KEY.encode(), timestamp.encode() + raw_body,
                                     hashlib.sha256).digest()).decode()
