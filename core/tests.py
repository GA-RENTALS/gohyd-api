from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.test import override_settings

from core.money import add_gst, extract_gst, format_inr, split_advance


class MoneyTests(SimpleTestCase):
    def test_document_example(self):
        s = split_advance(Decimal('5000'), 3000)
        self.assertEqual((s.advance, s.balance), (Decimal('1500.00'), Decimal('3500.00')))

    def test_split_always_sums(self):
        for bp in (1, 333, 3333, 6667, 9999):
            s = split_advance(Decimal('999.99'), bp)
            self.assertEqual(s.advance + s.balance, s.total)

    def test_gst(self):
        self.assertEqual(add_gst(Decimal('1000'), 500).gross, Decimal('1050.00'))
        t = extract_gst(Decimal('1050'), 500)
        self.assertEqual((t.net, t.tax), (Decimal('1000.00'), Decimal('50.00')))

    def test_inr_format(self):
        self.assertEqual(format_inr(Decimal('123456.5')), '₹1,23,456.50')


class DemoDataCommandSafetyTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_demo_seed_is_refused_outside_debug(self):
        with self.assertRaisesMessage(CommandError, 'Demo data is disabled'):
            call_command('seed_demo_data')
