"""Shared bits for calls to Meta's WhatsApp Cloud API."""
import hashlib
import hmac
import os


def graph_params(token):
    """
    Query parameters every Graph API call needs. When the Meta app has "Require App Secret"
    on (App settings → Advanced), each call must carry appsecret_proof: an HMAC-SHA256 of the
    access token, keyed with the app secret. Set WHATSAPP_APP_SECRET to send it.
    """
    secret = os.getenv('WHATSAPP_APP_SECRET')
    if not (secret and token):
        return {}
    proof = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    return {'appsecret_proof': proof}
