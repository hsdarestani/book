from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .customer_identity import duplicate_customer_count, find_customer, grouped_customers_for_display, unique_customer_count
from .models import Appointment, Customer, Service, StaffMember


class DuplicatePatientSafetyTests(TestCase):
    def test_patient_list_groups_duplicates_without_deleting_rows(self):
        first = Customer.objects.create(
            first_name="Sophie",
            last_name="Muster",
            phone="+49 160 1112233",
            email="sophie@example.com",
        )
        duplicate = Customer.objects.create(
            first_name="Sofi",
            last_name="Muster Alt",
            phone="0160 1112233",
            email="sophie.legacy@example.com",
        )

        rows = grouped_customers_for_display(Customer.objects.all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].display_profile_count, 2)
        self.assertEqual(set(rows[0].display_group_ids), {first.pk, duplicate.pk})
        self.assertEqual(Customer.objects.count(), 2)

        by_legacy_email = grouped_customers_for_display(Customer.objects.all(), query="sophie.legacy@example.com")
        self.assertEqual(len(by_legacy_email), 1)
        self.assertEqual(set(by_legacy_email[0].display_group_ids), {first.pk, duplicate.pk})
        self.assertEqual(Customer.objects.count(), 2)

    def test_patient_count_groups_same_phone_even_if_name_or_email_differs(self):
        first = Customer.objects.create(
            first_name="Anna",
            last_name="Muster",
            phone="+49 170 1234567",
            email="anna@example.com",
        )
        duplicate = Customer.objects.create(
            first_name="Ana",
            last_name="Mustermann",
            phone="0170 1234567",
            email="anna.second@example.com",
        )
        service = Service.objects.create(name="Count Test", slug="count-test")
        staff = StaffMember.objects.create(display_name="Count Team")
        staff.services.add(service)
        starts = timezone.now() + timedelta(days=3)
        appointment = Appointment.objects.create(
            customer=duplicate,
            service=service,
            staff=staff,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=30),
            status="confirmed",
            source="simplybook",
        )

        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual(unique_customer_count(Customer.objects.all()), 1)
        self.assertEqual(duplicate_customer_count(Customer.objects.all()), 1)

        first.refresh_from_db()
        duplicate.refresh_from_db()
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_id, duplicate.pk)
        self.assertTrue(Customer.objects.filter(pk=first.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=duplicate.pk).exists())

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
        # SimplyBook style matching with a changed e-mail still resolves the
        # existing person by exact phone + first/last name instead of creating a third row.
        matched = find_customer(
            email="anna-new@example.com",
            phone="0170 1234567",
            first_name="Anna",
            last_name="Muster",
        )
        self.assertIn(matched.pk, {first.pk, duplicate.pk})

        call_command("dedupe_customers")

        self.assertEqual(Customer.objects.count(), 2)
        appointment.refresh_from_db()
        self.assertEqual(appointment.customer_id, duplicate.pk)
        self.assertTrue(Customer.objects.filter(pk=first.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=duplicate.pk).exists())
