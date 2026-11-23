"""Regression coverage for clinic-wide Sunday closure across public booking channels."""
from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import Appointment, Customer, DailyAvailabilityOverride, Service, StaffMember, WorkingHour
from .services import available_slots, create_appointment


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class SundayBookingPolicyTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(
            name="Sunday closure test", slug="test-clinic-sunday",
            duration_minutes=15, buffer_minutes=0, active=True, bookable=True,
        )
        self.staff = StaffMember.objects.create(display_name="Test Sunday clinician", active=True)
        self.staff.services.add(self.service)
        today = timezone.localdate()
        days_to_sunday = (6 - today.weekday()) % 7 or 7
        self.sunday = today + timedelta(days=days_to_sunday)
        self.monday = self.sunday + timedelta(days=1)
        for weekday in (0, 6):
            WorkingHour.objects.create(
                staff=self.staff, weekday=weekday,
                start_time=time(9), end_time=time(13), active=True,
            )
        self.customer = Customer.objects.create(
            first_name="Sunday", last_name="Tester", email="sunday-test@example.invalid",
        )

    def starts_at(self, day):
        return timezone.make_aware(
            datetime.combine(day, time(10)), timezone.get_current_timezone()
        )

    def test_sunday_is_closed_even_with_explicit_open_override(self):
        DailyAvailabilityOverride.objects.create(
            staff=self.staff, date=self.sunday, closed=False,
            start_time_1=time(9), end_time_1=time(13),
        )
        self.assertEqual(available_slots(self.service, self.staff, self.sunday), [])

        public = self.client.get("/api/availability/", {
            "service_id": self.service.pk, "staff_id": self.staff.pk,
            "date": self.sunday.isoformat(),
        })
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json()["slots"], [])

        mobile = self.client.get("/api/mobile/slots/", {
            "service_id": self.service.pk, "day": self.sunday.isoformat(),
        })
        self.assertEqual(mobile.status_code, 200)
        self.assertEqual(mobile.json()["slots"], [])

        with self.assertRaisesMessage(ValueError, "time_not_available"):
            create_appointment(
                customer=self.customer, staff=self.staff, service=self.service,
                starts_at=self.starts_at(self.sunday),
            )
        self.assertFalse(Appointment.objects.exists())

    def test_monday_remains_bookable_without_other_changes(self):
        slots = available_slots(self.service, self.staff, self.monday)
        self.assertIn(self.starts_at(self.monday), slots)
