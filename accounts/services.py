import logging
import os

import requests

from core.whatsapp import graph_params

logger = logging.getLogger(__name__)


class WhatsAppService:
    """Direct Meta WhatsApp Cloud API (no BSP). Sends approved message templates."""

    @staticmethod
    def configured() -> bool:
        return bool(os.getenv('WHATSAPP_API_URL') and os.getenv('WHATSAPP_ACCESS_TOKEN'))

    @staticmethod
    def _post(payload, *, sensitive: bool):
        url, token = os.getenv('WHATSAPP_API_URL'), os.getenv('WHATSAPP_ACCESS_TOKEN')
        if not (url and token):
            raise RuntimeError('WhatsApp Cloud API is not configured')
        r = requests.post(url, headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
                          params=graph_params(token), json=payload, timeout=10)
        if r.status_code not in (200, 201):
            if sensitive:
                logger.error('WhatsApp API error: %s', r.status_code)  # never log the body: it contains the OTP
                raise RuntimeError(f'WhatsApp send failed: HTTP {r.status_code}')
            try:
                err = r.json().get('error', {})
            except ValueError:
                err = {}
            logger.error('WhatsApp API error: %s code=%s %s', r.status_code, err.get('code'), str(err.get('message', ''))[:200])
            raise RuntimeError(f"WhatsApp send failed: HTTP {r.status_code} (code {err.get('code')}): {str(err.get('message', ''))[:160]}")
        return r.json()

    @staticmethod
    def send_otp(phone_number: str, otp: str, language=None):
        """The approved authentication template (code in the body and on the copy-code button).

        The language must match how the template was registered with Meta (for example `en` or `en_US`): WHATSAPP_TEMPLATE_LANGUAGE.
        """
        language = language or os.getenv('WHATSAPP_TEMPLATE_LANGUAGE', 'en')
        payload = {
            'messaging_product': 'whatsapp', 'to': phone_number.replace('+', '').strip(), 'type': 'template',
            'template': {'name': os.getenv('WHATSAPP_TEMPLATE_NAME', 'gohyd_otp'), 'language': {'code': language}, 'components': [
                {'type': 'body', 'parameters': [{'type': 'text', 'text': str(otp)}]},
                {'type': 'button', 'sub_type': 'url', 'index': '0', 'parameters': [{'type': 'text', 'text': str(otp)}]},
            ]},
        }
        return WhatsAppService._post(payload, sensitive=True)

    @staticmethod
    def send_template(phone_number: str, template_name: str, language: str, body_params):
        """Any approved template whose body has {{1}}, {{2}}, … variables. `body_params` is the ordered list of values."""
        template = {'name': template_name, 'language': {'code': language}}
        if body_params:
            template['components'] = [{'type': 'body', 'parameters': [{'type': 'text', 'text': str(p)} for p in body_params]}]
        payload = {'messaging_product': 'whatsapp', 'to': phone_number.replace('+', '').strip(), 'type': 'template', 'template': template}
        return WhatsAppService._post(payload, sensitive=False)
