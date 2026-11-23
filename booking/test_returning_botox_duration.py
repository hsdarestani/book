from django.test import TestCase

from .models import Service


class ReturningBotoxDurationTests(TestCase):
    def test_seeded_returning_patient_service_occupies_fifteen_minutes(self):
        service = Service.objects.get(slug="botox-bestandspatient")
        self.assertEqual(service.duration_minutes, 15)
        self.assertEqual(service.buffer_minutes, 0)
        self.assertEqual(service.duration_minutes + service.buffer_minutes, 15)
