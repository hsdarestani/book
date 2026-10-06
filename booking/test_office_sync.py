import json

from django.test import TestCase, override_settings

from .models import Customer, Service


@override_settings(PATIENT_SYNC_TOKEN="integration-secret")
class OfficeSyncTests(TestCase):
    def headers(self):
        return {"HTTP_X_AESTHETIC_PATIENT_SYNC": "integration-secret"}

    def test_customer_sync_is_idempotent_and_updates_contact(self):
        payload = {
            "email": "anna@example.com",
            "phone": "+49 151 1234567",
            "first_name": "Anna",
            "last_name": "Muster",
        }
        response = self.client.post(
            "/api/internal/customer-sync/",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["created"])

        payload["phone"] = "+49 151 7654321"
        response = self.client.post(
            "/api/internal/customer-sync/",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Customer.objects.get().phone, "+49 151 7654321")

    def test_billing_catalog_exposes_canonical_services(self):
        Service.objects.create(
            name="Hydra Facial",
            slug="hydra-facial",
            description="Test",
            duration_minutes=60,
            buffer_minutes=10,
            price_label="119 €",
            active=True,
            bookable=True,
            requires_confirmation=False,
        )
        response = self.client.get(
            "/api/internal/billing-catalog/",
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        service = next(item for item in data["services"] if item["slug"] == "hydra-facial")
        self.assertEqual(service["slug"], "hydra-facial")
        self.assertTrue(service["bookable"])
