from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from core.testing import TenantTestCase
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import LoginHistory, OtpVerificationRecord, User, normalize_phone


@override_settings(OTP_LOG_IN_CONSOLE=False, OTP_SEND_INLINE=False)   # these tests exercise the queued (production) path
class OtpTests(TenantTestCase):
    phone = '+919876543210'

    def setUp(self):
        cache.clear()
        self.c = APIClient()
        self.sent = []
        patcher = mock.patch('accounts.views.send_whatsapp_otp_task.delay', side_effect=lambda p, o: self.sent.append((p, o)))
        patcher.start(); self.addCleanup(patcher.stop)

    def request(self):
        return self.c.post('/api/v1/auth/request-otp/', {'phone_number': '98765 43210'}, format='json')

    def verify(self, code):
        return self.c.post('/api/v1/auth/verify-otp/', {'phone_number': self.phone, 'otp': code}, format='json')

    def test_phone_normalisation(self):
        self.assertEqual(normalize_phone('09876543210'), self.phone)

    def test_full_login_flow_and_hash_only_storage(self):
        self.assertEqual(self.request().status_code, 200)
        code = self.sent[-1][1]
        rec = OtpVerificationRecord.objects.get()
        self.assertNotIn(code, rec.code_hash)                  # only a hash is stored
        r = self.verify(code)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['is_new_user'])
        self.assertIn('access', r.data)
        self.assertEqual(self.verify(code).status_code, 400)   # a code works once
        me = self.c.get('/api/v1/me/', HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        self.assertEqual(me.data['phone_number'], self.phone)

    def test_resend_throttled(self):
        self.request()
        self.assertEqual(self.request().status_code, 429)

    def test_attempt_limit_locks_the_code(self):
        self.request()
        code = self.sent[-1][1]
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.assertEqual(self.verify(wrong).status_code, 400)
        self.assertEqual(self.verify(code).status_code, 400)   # right code no longer works after lockout

    def test_expired_code_rejected(self):
        self.request()
        code = self.sent[-1][1]
        OtpVerificationRecord.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(code).status_code, 400)

    def test_new_code_invalidates_old(self):
        self.request()
        old = self.sent[-1][1]
        cache.clear()
        self.request()
        new = self.sent[-1][1]
        if old != new:
            self.assertEqual(self.verify(old).status_code, 400)
        self.assertEqual(self.verify(new).status_code, 200)

    def test_failures_are_logged_and_disabled_users_blocked(self):
        User.objects.create_user(self.phone, is_active=False)
        self.request()
        self.assertEqual(self.verify(self.sent[-1][1]).status_code, 403)
        self.assertTrue(LoginHistory.objects.filter(success=False, reason='account_disabled').exists())


@override_settings(OTP_LOG_IN_CONSOLE=False, OTP_SEND_INLINE=True)
class DevelopmentOtpSendingTests(TenantTestCase):
    """In development the code is sent during the request (no worker needed) and falls back to the console if Meta refuses."""

    def setUp(self):
        cache.clear()

    def request(self):
        return APIClient().post('/api/v1/auth/request-otp/', {'phone_number': '98765 43210'}, format='json')

    def test_sends_immediately(self):
        with mock.patch('accounts.views.WhatsAppService.send_otp') as send:
            r = self.request()
        self.assertEqual(r.status_code, 200)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], '+919876543210')

    def test_still_succeeds_and_logs_the_code_when_meta_refuses(self):
        with mock.patch('accounts.views.WhatsAppService.send_otp', side_effect=RuntimeError('rejected')), \
                self.assertLogs('accounts.views', level='WARNING') as logs:
            r = self.request()
        self.assertEqual(r.status_code, 200)
        self.assertIn('Development sign-in code', logs.output[0])
