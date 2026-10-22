"""Regression coverage for real SimplyBook identities and safe placeholder cleanup."""
import io
import os
from datetime import timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from .models import (
    Appointment, Customer, PatientRecord, Service, SimplyBookClientLink,
    StaffMember,
)


class SimplyBookReliableSyncTests(TestCase):
    def setUp(self):
        self.environment = {
            "SIMPLYBOOK_COMPANY_LOGIN": "test-company",
            "SIMPLYBOOK_USER_LOGIN": "test-user",
            "SIMPLYBOOK_API_USER_KEY": "test-secret",
        }
        self.start = timezone.now() + timedelta(days=6)

    def response(self, url, method, params, *args, **kwargs):
        if method == "getUserToken":
            return "fake-token"
        if method == "getCompanyTimezoneOffset":
            return {"timezone": "Europe/Berlin"}
        if method == "getUnitList":
            return [{"id": 1, "name": "Source clinic"}]
        if method == "getEventList":
            return [{"id": 7, "name": "Source service", "duration": 30, "is_active": 1}]
        if method == "getClientList":
            return [
                {"id": "101", "name": "Anna Alpha", "email": "shared@example.com", "phone": "+491701112222"},
                {"id": "102", "name": "Berta Beta", "email": "shared@example.com", "phone": "+491701113333"},
            ]
        if method == "getBookings":
            base = self.start.replace(second=0, microsecond=0)
            return [
                {"id": "501", "client_id": "101", "event_id": "7",
                 "start_date": base.strftime("%Y-%m-%d %H:%M:%S"),
                 "end_date": (base+timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                 "is_confirm": "1"},
                {"id": "502", "client_id": "102", "event_id": "7",
                 "start_date": (base+timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
                 "end_date": (base+timedelta(hours=1,minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                 "is_confirm": "1"},
                {"id": "503", "client_id": "", "event_id": "7",
                 "start_date": (base+timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                 "end_date": (base+timedelta(hours=2,minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
                 "is_confirm": "1"},
            ]
        return {}

    @patch("booking.management.commands.simplybook_import.rpc")
    def test_repeated_import_preserves_two_people_sharing_email_and_anonymous_booking(self, rpc):
        rpc.side_effect = self.response
        with patch.dict(os.environ, self.environment):
            call_command("simplybook_import", strict=True, stdout=io.StringIO())
            initial = list(Appointment.objects.order_by("idempotency_key").values_list("customer_id", flat=True))
            self.assertEqual(len(initial), 3)
            self.assertEqual(len(set(initial)), 3)
            self.assertEqual(SimplyBookClientLink.objects.count(), 2)
            self.assertEqual(Customer.objects.count(), 3)
            call_command("simplybook_import", strict=True, stdout=io.StringIO())
        self.assertEqual(Customer.objects.count(), 3)
        self.assertEqual(SimplyBookClientLink.objects.count(), 2)
        self.assertEqual(initial, list(Appointment.objects.order_by("idempotency_key").values_list("customer_id", flat=True)))
        self.assertEqual(Customer.objects.filter(email="simplybook-booking-503@invalid.local").count(), 1)

    @patch("booking.management.commands.simplybook_import.rpc")
    def test_missing_source_service_rolls_back_every_change(self, rpc):
        def missing_event(url, method, params, *args, **kwargs):
            if method == "getEventList":
                return []
            return self.response(url, method, params, *args, **kwargs)
        rpc.side_effect = missing_event
        with patch.dict(os.environ, self.environment):
            with self.assertRaises(CommandError):
                call_command("simplybook_import", strict=True, stdout=io.StringIO())
        self.assertEqual(Customer.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(SimplyBookClientLink.objects.count(), 0)


class SimplyBookCleanupTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(name="Test", slug="clean-source-test")
        self.staff = StaffMember.objects.create(display_name="Test therapist")
        self.staff.services.add(self.service)
        self.keeper = Customer.objects.create(
            first_name="SimplyBook", last_name="Kunde", phone="",
            email="simplybook-booking-503@invalid.local")
        self.one = Customer.objects.create(
            first_name="SimplyBook", last_name="Kunde", phone="",
            email="simplybook-booking-503@invalid.local")
        self.two = Customer.objects.create(
            first_name="SimplyBook", last_name="Kunde", phone="",
            email="simplybook-booking-503@invalid.local")
        self.protected = Customer.objects.create(
            first_name="SimplyBook", last_name="Kunde", phone="",
            email="simplybook-booking-503@invalid.local")
        PatientRecord.objects.create(customer=self.protected, kind="note", title="Do not delete")
        self.real = Customer.objects.create(
            first_name="Anna", last_name="Alpha", phone="+491701112222",
            email="anna@example.com")
        start = timezone.now() + timedelta(days=2)
        Appointment.objects.create(
            customer=self.keeper, service=self.service, staff=self.staff,
            idempotency_key="simplybook-503",
            starts_at=start, ends_at=start+timedelta(minutes=30))

    def test_dry_run_preserves_everything(self):
        out = io.StringIO()
        call_command("cleanup_simplybook_orphans", stdout=out)
        self.assertIn('"safe_orphan_candidates": 2', out.getvalue())
        self.assertEqual(Customer.objects.count(), 5)

    def test_backup_gate_and_protected_related_records(self):
        with self.assertRaises(CommandError):
            call_command("cleanup_simplybook_orphans", apply=True, stdout=io.StringIO())
        with NamedTemporaryFile() as backup:
            backup.write(b"backup" * 300)
            backup.flush()
            out = io.StringIO()
            call_command("cleanup_simplybook_orphans", apply=True, backup_file=backup.name, stdout=out)
        self.assertIn('"deleted": 2', out.getvalue())
        self.assertFalse(Customer.objects.filter(pk=self.one.pk).exists())
        self.assertFalse(Customer.objects.filter(pk=self.two.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=self.keeper.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=self.protected.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=self.real.pk).exists())
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(PatientRecord.objects.count(), 1)
