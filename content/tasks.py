from celery import shared_task
from django.utils import timezone

from . import models as m


@shared_task(name='content.tasks.publish_due')
def publish_due():
    """Flip SCHEDULED content whose time has come to PUBLISHED, re-checking the translation gate."""
    n = 0
    for model in (m.Destination, m.Blog, m.CmsPage):
        for obj in model.objects.filter(status=m.ContentStatus.SCHEDULED, publish_at__lte=timezone.now()):
            try:
                obj.publish()
                n += 1
            except Exception:
                continue
    return n
