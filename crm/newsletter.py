"""Newsletter unsubscribe links.

Mailings are sent from an outside email tool with the list from Marketing → Subscribers → Export CSV. Each row carries
its own unsubscribe link: a signed token naming the subscription, so it can't be guessed or changed to another address,
and it never expires (people click old emails).
"""
from django.conf import settings
from django.core import signing
from django.utils import timezone

from .models import NewsletterSubscription

_SALT = 'crm.newsletter.unsubscribe'


def unsubscribe_token(subscription):
    return signing.dumps(subscription.pk, salt=_SALT)


def unsubscribe_url(subscription):
    return f'{settings.FRONTEND_ORIGIN}/newsletter/unsubscribe?token={unsubscribe_token(subscription)}'


def unsubscribe(token):
    """Unsubscribe the address the token names. Returns the subscription, or None for a token that isn't ours.
    Clicking twice is harmless: the first date is kept."""
    try:
        pk = signing.loads(token, salt=_SALT)
    except signing.BadSignature:
        return None
    subscription = NewsletterSubscription.objects.filter(pk=pk).first()
    if subscription and subscription.unsubscribed_at is None:
        subscription.unsubscribed_at = timezone.now()
        subscription.save(update_fields=['unsubscribed_at', 'updated_at'])
    return subscription
