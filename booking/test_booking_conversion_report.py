from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from booking.models import Appointment, Customer, Service, StaffMember


class BookingConversionReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = Customer.objects.create(first_name="Synthetic", last_name="Fixture", email="fixture@example.invalid")
        cls.service = Service.objects.create(name="Fixture", slug="conversion-report-fixture")
        cls.staff = StaffMember.objects.create(display_name="Fixture")

    def add_booking(self, created, source, status, key=None):
        starts = created + timedelta(days=30)
        appointment = Appointment.objects.create(
            customer=self.customer, service=self.service, staff=self.staff,
            starts_at=starts, ends_at=starts + timedelta(minutes=30),
            source=source, status=status, idempotency_key=key,
        )
        Appointment.objects.filter(pk=appointment.pk).update(created_at=created)

    def report(self, start="2026-11-01", end="2026-11-30"):
        output = StringIO()
        call_command("booking_conversion_report", start=start, end=end, stdout=output)
        return json.loads(output.getvalue())

    def test_current_status_and_imported_records_are_separate(self):
        stamp = datetime(2026, 11, 15, 12, tzinfo=ZoneInfo("Europe/Berlin"))
        for source, status, key in [
            ("web", "confirmed", "web-fixture"),
            ("app", "completed", "app-fixture"),
            ("web", "new", None),
            ("app", "cancelled", None),
            ("web", "no_show", None),
            ("admin", "confirmed", "simplybook-fixture"),
            ("app", "confirmed", "legacy-aesthetic-fixture"),
            ("admin", "confirmed", None),
        ]:
            self.add_booking(stamp, source, status, key)
        result = self.report()
        self.assertEqual(result["online_created"], 5)
        self.assertEqual(result["online_confirmed_or_completed"], 2)
        self.assertEqual(result["online_pending"], 1)
        self.assertEqual(result["online_cancelled"], 1)
        self.assertEqual(result["online_no_show"], 1)
        self.assertEqual(result["channels"]["imported"]["confirmed"], 2)
        self.assertEqual(result["channels"]["admin"]["confirmed"], 1)
        self.assertNotIn("fixture@example.invalid", json.dumps(result))

    def test_berlin_date_boundaries(self):
        berlin = ZoneInfo("Europe/Berlin")
        lower = datetime(2026, 11, 1, 0, tzinfo=berlin)
        upper = datetime(2026, 12, 1, 0, tzinfo=berlin)
        for stamp in (lower - timedelta(seconds=1), lower, upper - timedelta(seconds=1), upper):
            self.add_booking(stamp, "web", "confirmed")
        self.assertEqual(self.report()["online_confirmed_or_completed"], 2)

    def test_invalid_and_empty_range(self):
        with self.assertRaises(CommandError):
            self.report(start="2026-12-01", end="2026-11-30")
        self.assertEqual(self.report()["online_created"], 0)


class BookingConversionDashboardTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.manager = User.objects.create_user(username="report-manager", is_staff=True, is_superuser=True)
        self.staff_user = User.objects.create_user(username="report-staff", is_staff=True)
        self.normal_user = User.objects.create_user(username="report-normal")
        self.url = "/verwaltung/buchungsstatistik/"

    def test_anonymous_and_non_manager_cannot_access(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for user in (self.normal_user, self.staff_user):
            self.client.force_login(user)
            self.assertIn(self.client.get(self.url).status_code, (302, 403))

    def test_manager_can_view_aggregate_and_cache_is_disabled(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.url, {"start": "2026-11-01", "end": "2026-11-30"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Buchungsstatistik")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.context["report"]["online_created"], 0)

    def test_invalid_range_and_post_rejected(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url, {"start": "2026-12-01", "end": "2026-11-30"}).status_code, 400)
        self.assertEqual(self.client.post(self.url).status_code, 405)
