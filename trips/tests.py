from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_trip, TenantTestCase


class TripApiTests(TenantTestCase):
    def test_published_trip_listed_with_schedule_and_effective_advance(self):
        make_trip('ananthagiri', advance_bp=2500)
        r = APIClient().get('/api/v1/trips/')
        self.assertEqual(r.data['count'], 1)
        d = APIClient().get('/api/v1/trips/ananthagiri/').data
        self.assertEqual(d['schedules'][0]['advance_basis_points'], 2500)

    def test_admin_pages_load(self):
        U = get_user_model()
        su = U.objects.create_superuser('+919999999999', password='pw-12345-xyz')
        c = self.client; c.force_login(su)
        for path in ('/admin/?classic=1', '/admin/bookings/booking/', '/admin/payments/payment/', '/admin/trips/trip/add/', '/admin/content/destination/add/',
                     '/admin/crm/enquiry/', '/admin/tracking/visitorevent/', '/admin/core/auditlog/', '/admin/accounts/user/'):
            self.assertEqual(c.get(path).status_code, 200, path)
