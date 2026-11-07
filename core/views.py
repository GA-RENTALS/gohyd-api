from django.conf import settings
from django.http import HttpResponse
from django.utils.html import escape


def home(request):
    """A small landing page at the backend's own address, so there is always a way in to the Django side."""
    links = [
        ('Staff admin panel', settings.ADMIN_PANEL_URL, 'The new admin (Next.js). Sign in with a WhatsApp code or a password.'),
        ('Django admin', '/admin/?classic=1', 'The stock Django admin, a fallback for developers. Sign in with phone number (+91…) and password.'),
        ('API documentation', '/api/docs/', 'Every public and staff endpoint, with try-it-out.'),
        ('API schema', '/api/schema/', 'The machine-readable OpenAPI description.'),
        ('Public website', settings.SPECTACULAR_SETTINGS.get('SITE_URL', ''), 'The customer-facing site.'),
    ]
    items = ''.join(
        f'<li><a href="{escape(url)}"><strong>{escape(name)}</strong></a><br><span>{escape(note)}</span></li>' for name, url, note in links if url)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GoHyderabad backend</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:640px;margin:48px auto;padding:0 20px;color:#1a1b15}}
h1{{margin-bottom:4px}}p{{color:#5f6154}}ul{{list-style:none;padding:0}}li{{padding:14px 0;border-top:1px solid #e6e6e3}}
a{{color:#435a33}}span{{color:#5f6154;font-size:14px}}</style></head>
<body><h1>GoHyderabad backend</h1><p>Django REST API. This page only lists where things are.</p><ul>{items}</ul></body></html>"""
    return HttpResponse(page)
