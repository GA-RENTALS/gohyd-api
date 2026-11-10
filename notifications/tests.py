import os
from unittest import mock

from celery.exceptions import Retry

from accounts.services import WhatsAppService
from core.testing import TenantTestCase, make_user

from .models import Channel, NotificationDeliveryLog, NotificationEvent, NotificationFailure, NotificationJob, NotificationTemplate
from .services import template_params
from .tasks import deliver

ENV = {'WHATSAPP_API_URL': 'https://graph.example.test/v21.0/123/messages', 'WHATSAPP_ACCESS_TOKEN': 'test-token'}


class WhatsAppServiceTests(TenantTestCase):
    def test_template_payload_has_variables_in_order(self):
        with mock.patch.dict(os.environ, ENV), mock.patch('accounts.services.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'messages': [{'id': 'wamid.1'}]}
            result = WhatsAppService.send_template('+919876500001', 'gohyd_balance', 'en', ['Asha', 'GH-123', '1,400', '30 Nov 2026'])
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['to'], '919876500001')                       # no "+" for WhatsApp
        self.assertEqual(payload['template']['name'], 'gohyd_balance')
        self.assertEqual(payload['template']['language'], {'code': 'en'})
        self.assertEqual([p['text'] for p in payload['template']['components'][0]['parameters']], ['Asha', 'GH-123', '1,400', '30 Nov 2026'])
        self.assertEqual(result['messages'][0]['id'], 'wamid.1')

    def test_meta_error_is_raised_with_its_code(self):
        with mock.patch.dict(os.environ, ENV), mock.patch('accounts.services.requests.post') as post:
            post.return_value.status_code = 400
            post.return_value.json.return_value = {'error': {'code': 132001, 'message': 'Template name does not exist'}}
            with self.assertRaisesMessage(RuntimeError, '132001'):
                WhatsAppService.send_template('+919876500001', 'nope', 'en', [])

    def test_variables_follow_the_event_order_and_never_empty(self):
        ctx = {'name': 'Asha', 'reference': 'GH-1', 'amount': '1400.00', 'due_date': '30 Nov 2026'}
        self.assertEqual(template_params('balance_reminder', ctx), ['Asha', 'GH-1', '1400.00', '30 Nov 2026'])
        self.assertEqual(template_params('payment_receipt', {'name': ''}), ['-', '-'])   # WhatsApp rejects empty variables


class DeliveryTests(TenantTestCase):
    def setUp(self):
        self.user = make_user('+919876500002', full_name='Asha')
        self.n = 0

    def job(self, event=NotificationEvent.BALANCE_REMINDER):
        self.n += 1
        return NotificationJob.objects.create(user=self.user, event=event, channel=Channel.WHATSAPP, language='en', dedupe_key=f'k{self.n}',
                                              context={'name': 'Asha', 'reference': 'GH-9', 'amount': '500', 'due_date': '1 Dec 2026'})

    def template(self, name='gohyd_balance', event=NotificationEvent.BALANCE_REMINDER):
        return NotificationTemplate.objects.create(event=event, channel=Channel.WHATSAPP, provider_template_name=name, is_active=True)

    def run_deliver(self, job, **kw):
        deliver.apply(args=[str(job.pk), str(self.tenant.pk)], **kw)
        job.refresh_from_db()
        return job

    def test_sends_and_records_the_message_id(self):
        self.template()
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=True), \
                mock.patch.object(WhatsAppService, 'send_template', return_value={'messages': [{'id': 'wamid.ABC'}]}) as send:
            job = self.run_deliver(job)
        self.assertEqual(job.status, NotificationJob.Status.SENT)
        send.assert_called_once_with('+919876500002', 'gohyd_balance', 'en', ['Asha', 'GH-9', '500', '1 Dec 2026'])
        self.assertEqual(NotificationDeliveryLog.objects.get(job=job).provider_message_id, 'wamid.ABC')

    def test_skipped_with_a_reason_when_no_template_name_is_set(self):
        self.template(name='')
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=True), mock.patch.object(WhatsAppService, 'send_template') as send:
            job = self.run_deliver(job)
        self.assertEqual(job.status, NotificationJob.Status.SKIPPED)
        send.assert_not_called()
        self.assertIn('template name', NotificationFailure.objects.get(job=job).error)

    def test_skipped_when_whatsapp_is_not_configured(self):
        self.template()
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=False):
            job = self.run_deliver(job)
        self.assertEqual(job.status, NotificationJob.Status.SKIPPED)

    def test_marked_failed_after_the_last_retry(self):
        self.template()
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=True), \
                mock.patch.object(WhatsAppService, 'send_template', side_effect=RuntimeError('boom')):
            job = self.run_deliver(job, retries=deliver.max_retries)
        self.assertEqual(job.status, NotificationJob.Status.FAILED)
        self.assertEqual(NotificationFailure.objects.filter(job=job).count(), 1)

    def test_transient_delivery_error_is_retried(self):
        self.template()
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=True), \
                mock.patch.object(WhatsAppService, 'send_template', side_effect=RuntimeError('temporary')):
            with mock.patch.object(deliver, 'retry', side_effect=Retry()) as retry:
                with self.assertRaises(Retry):
                    deliver.run(str(job.pk), str(self.tenant.pk))
        job.refresh_from_db()
        retry.assert_called_once()
        self.assertEqual(job.status, NotificationJob.Status.QUEUED)

    def test_a_sent_job_is_not_sent_twice(self):
        self.template()
        job = self.job()
        with mock.patch.object(WhatsAppService, 'configured', return_value=True), \
                mock.patch.object(WhatsAppService, 'send_template', return_value={'messages': [{'id': 'w'}]}) as send:
            self.run_deliver(job)
            self.run_deliver(job)
        self.assertEqual(send.call_count, 1)
