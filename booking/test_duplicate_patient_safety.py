from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .customer_identity import duplicate_customer_count, unique_customer_count
from .models import Appointment, Customer, Service, StaffMember


class DuplicatePatientSafetyTests(TestCase):
    def test_duplicate_count_is_non_destructive_and_keeps_reservations(self):
        first = Customer.objects.create(
            first_name="Anna",
            last_name="Muster",
            phone="+49 170 1234567",
            email="anna@example.com",
        )
        duplicate = Customer.objects.create(
            first_name="Anna",
            last_name="Muster",
            phone="0170 1234567",
            email="ANNA@example.com",
        )
        service = Service.objects.create(name="Testbehandlung", slug="duplicate-test")
        staff = StaffMember.objects.create(display_name="Test Team")
        staff.services.add(service)
        starts = timezone.now() + timedelta(days=2)
        appointment = Appointment.objects.create(
            customer=duplicate,
            service=service,
            staff=staff,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=30),
            status="confirmed",
            source="admin",
        )

        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual(unique_customer_count(Customer.objects.all()), 1)
        self.assertEqual(duplicate_customer_count(Customer.objects.all()), 1)

        call_command("dedupe_customers")

        self.assertEqual(Customer.objects.count(), 2)
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_id, duplicate.pk)
        self.assertTrue(Customer.objects.filter(pk=first.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=duplicate.pk).exists())
