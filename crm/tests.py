from core.testing import TenantTestCase
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Enquiry


class EnquiryTests(TenantTestCase):
    def test_enquiry_requires_a_way_to_reply(self):
        self.assertEqual(APIClient().post('/api/v1/enquiries/', {'name': 'A'}, format='json').status_code, 400)

    def test_enquiry_saved_with_source(self):
        r = APIClient().post('/api/v1/enquiries/', {'name': 'A', 'phone': '9876543210', 'consent_to_contact': True}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Enquiry.objects.get().source.name, 'website')
