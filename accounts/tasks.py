from celery import shared_task

from .services import WhatsAppService


@shared_task(bind=True, max_retries=5, retry_backoff=True, retry_backoff_max=120, name='accounts.tasks.send_whatsapp_otp')
def send_whatsapp_otp_task(self, phone_number, otp):
    # SMS fallback (section 4.1) plugs in here once a provider is chosen: catch the final failure and send via SMS.
    try:
        return WhatsAppService.send_otp(phone_number, otp)
    except Exception as exc:
        raise self.retry(exc=exc)
