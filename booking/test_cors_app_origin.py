from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from booking.cors import MobileApiCorsMiddleware


class CustomerClubBookingCorsTests(SimpleTestCase):
    def setUp(self):
        self.requests = RequestFactory()
        self.middleware = MobileApiCorsMiddleware(lambda request: HttpResponse('ok'))

    def test_official_web_app_can_query_cancellation_permissions(self):
        origin = 'https://app.a-esthetic.de'
        req = self.requests.options('/api/mobile/booking/manageable/', HTTP_ORIGIN=origin)
        result = self.middleware(req)
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result['Access-Control-Allow-Origin'], origin)
        self.assertIn('Authorization', result['Access-Control-Allow-Headers'])

    def test_customer_app_can_post_cancellation(self):
        origin = 'https://app.a-esthetic.de'
        req = self.requests.options('/api/mobile/booking/00000000-0000-0000-0000-000000000000/change/', HTTP_ORIGIN=origin)
        result = self.middleware(req)
        self.assertEqual(result.status_code, 204)
        self.assertIn('POST', result['Access-Control-Allow-Methods'])

    def test_unknown_origin_stays_blocked(self):
        req = self.requests.options('/api/mobile/booking/manageable/', HTTP_ORIGIN='https://untrusted.example')
        result = self.middleware(req)
        self.assertNotIn('Access-Control-Allow-Origin', result)

    def test_cors_not_enabled_for_admin_endpoints(self):
        req = self.requests.get('/verwaltung/', HTTP_ORIGIN='https://app.a-esthetic.de')
        result = self.middleware(req)
        self.assertNotIn('Access-Control-Allow-Origin', result)
