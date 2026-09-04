import json
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from .referral_models import ReferralEmailDelivery


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReferralRelayTests(TestCase):
    def post(self, payload, identity=None):
        identity = identity or {"email": "member@example.de", "name": "Paula Plus"}
        with mock.patch("booking.referral_relay._verify_customer_club_token", return_value=identity):
            return self.client.post(
                "/api/mobile/referral-email/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION="Bearer test-token-value-long-enough",
            )

    def test_sends_fixed_referral_email_and_audits_delivery(self):
        response = self.post({"invited_email": "friend@example.de", "referral_code": "APLUS-ABCDEF1234"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["email_sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["friend@example.de"])
        self.assertIn("APLUS-ABCDEF1234", mail.outbox[0].body)
        delivery = ReferralEmailDelivery.objects.get()
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(delivery.referrer_email, "member@example.de")

    def test_rejects_self_referral_and_invalid_code(self):
        self.assertEqual(
            self.post({"invited_email": "member@example.de", "referral_code": "APLUS-ABCDEF1234"}).status_code,
            409,
        )
        self.assertEqual(
            self.post({"invited_email": "friend@example.de", "referral_code": "bad"}).status_code,
            400,
        )

    def test_limits_sender_and_recipient(self):
        now = timezone.now()
        for i in range(5):
            ReferralEmailDelivery.objects.create(
                referrer_email="member@example.de",
                invited_email=f"friend{i}@example.de",
                referral_code=f"APLUS-ABCDE{i:05d}",
                status="sent",
                created_at=now - timedelta(minutes=i),
            )
        limited = self.post({"invited_email": "new@example.de", "referral_code": "APLUS-ABCDEF1234"})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"], "referral_daily_limit")
