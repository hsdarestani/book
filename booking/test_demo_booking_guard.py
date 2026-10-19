import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Appointment, Customer, Service, StaffMember


class DemoReservationSafetyTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name="Infusionstherapie", slug="infusionstherapie",
            duration_minutes=60, buffer_minutes=10, bookable=True, active=True
        )
        self.staff = StaffMember.objects.create(display_name="Test Provider", role="doctor", active=True)
        self.staff.services.add(self.service)

    def test_authenticated_demo_account_cannot_post_booking_or_send_push(self):
        demo_member = {
            "email": "demo@a-esthetic.de",
            "phone": "",
            "first_name": "Demo",
            "last_name": "Account",
        }
        payload = {
            "service_id": self.service.pk,
            "starts_at": (timezone.now() + timedelta(days=2)).isoformat()
        }
        with patch("booking.mobile_api._member", return_value=(demo_member, None)), (
            patch("booking.mobile_api.notify_booking_created") as notify
        ):
            response = self.client.post("/api/mobile/booking/", data=json.dumps(payload),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"], "demo_booking_disabled")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)
        notify.assert_not_called()

    def test_ordinary_customer_not_blocked_by_demo_guard(self):
        member = {"email": "real@example.de", "phone": "", "first_name": "Real", "last_name": "Person"}
        with patch("booking.mobile_api._member", return_value=(member, None)):
            response = self.client.post(
                "/api/mobile/booking/",
                data=json.dumps({"service_id": 999999, "starts_at": "2099-01-01T12:00:00+00:00"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["error"], "service_not_found")

    def test_web_booking_cannot_spoof_demo_email_to_create_real_appointment(self):
        body = {
            "service_id": self.service.pk,
            "staff_id": self.staff.pk,
            "starts_at": (timezone.now() + timedelta(days=2)).isoformat(),
            "first_name": "Demo", "last_name": "Account", "email": "demo@a-esthetic.de",
            "phone": "0000000000", "referral_source": "Website",
            "cancellation_terms_accepted": True, "privacy_accepted": True,
        }
        with patch("booking.api.notify_booking_created") as notify:
            response = self.client.post("/api/appointments/", data=json.dumps(body),
                                        content_type="application/json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json()["error"], "demo_booking_disabled")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Customer.objects.count(), 0)
        notify.assert_not_called()
