from django.test import TestCase

from .customer_identity import find_customer
from .models import Customer


class SimplyBookSyntheticIdentityTests(TestCase):
    def test_existing_synthetic_booking_customer_is_reused_without_contact_details(self):
        customer = Customer.objects.create(
            first_name="",
            last_name="",
            phone="",
            email="simplybook-booking-813@invalid.local",
        )

        result = find_customer(
            email="SIMPLYBOOK-BOOKING-813@invalid.local",
            phone="",
            first_name="",
            last_name="",
        )
        self.assertEqual(result.pk, customer.pk)
        self.assertEqual(Customer.objects.count(), 1)

    def test_existing_synthetic_client_customer_is_reused_without_contact_details(self):
        customer = Customer.objects.create(
            first_name="",
            last_name="",
            phone="",
            email="simplybook-client-91@invalid.local",
        )
        self.assertEqual(find_customer(email=customer.email).pk, customer.pk)

    def test_unknown_synthetic_email_does_not_match_another_customer(self):
        Customer.objects.create(
            first_name="",
            last_name="",
            phone="",
            email="simplybook-booking-813@invalid.local",
        )
        self.assertIsNone(find_customer(email="simplybook-booking-814@invalid.local"))

    def test_non_simplybook_placeholder_is_not_a_trusted_email_identity(self):
        Customer.objects.create(
            first_name="",
            last_name="",
            phone="",
            email="fake@invalid.local",
        )
        self.assertIsNone(find_customer(email="fake@invalid.local"))
