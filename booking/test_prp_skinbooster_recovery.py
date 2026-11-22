from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from booking.models import Service, StaffMember


class RestorePRPSkinboosterCommandTests(TestCase):
    def setUp(self):
        self.doctor = StaffMember.objects.create(
            display_name="Testärztin", role="doctor", active=True, sort_order=10,
        )
        self.skinbooster = Service.objects.create(
            name="Skinbooster", slug="skinbooster", duration_minutes=30,
            buffer_minutes=10, price_label="ab 220 €",
            active=False, bookable=False, requires_confirmation=False, sort_order=70,
        )

    def test_dry_run_never_mutates_services(self):
        out = StringIO()
        call_command("restore_prp_skinbooster", stdout=out)
        self.skinbooster.refresh_from_db()
        self.assertFalse(self.skinbooster.active)
        self.assertFalse(self.skinbooster.bookable)
        self.assertEqual(self.skinbooster.price_label, "ab 220 €")
        self.assertFalse(Service.objects.filter(slug="prp-behandlung").exists())
        self.assertIn("DRY RUN", out.getvalue())

    def test_write_requires_clinic_pricing_and_durations_and_active_doctor(self):
        with self.assertRaises(CommandError):
            call_command("restore_prp_skinbooster", apply=True)
        with self.assertRaises(CommandError):
            call_command("restore_prp_skinbooster", apply=True, confirm_prices=True)
        with self.assertRaises(CommandError):
            call_command(
                "restore_prp_skinbooster", apply=True, confirm_prices=True,
                prp_minutes=45, skinbooster_minutes=30, doctor_ids=[999999],
            )
        self.assertFalse(Service.objects.filter(slug="prp-behandlung").exists())

    def test_explicit_recovery_is_idempotent_and_stays_manual_confirmation(self):
        options = dict(
            apply=True, confirm_prices=True, prp_minutes=45,
            skinbooster_minutes=35, doctor_ids=[self.doctor.pk],
            stdout=StringIO(),
        )
        call_command("restore_prp_skinbooster", **options)
        call_command("restore_prp_skinbooster", **options)
        self.assertEqual(Service.objects.filter(slug="prp-behandlung").count(), 1)
        for slug, price, minutes in [
            ("prp-behandlung", "ab 350 €", 45),
            ("skinbooster", "ab 250 €", 35),
        ]:
            service = Service.objects.get(slug=slug)
            self.assertTrue(service.active)
            self.assertTrue(service.bookable)
            self.assertTrue(service.requires_confirmation)
            self.assertEqual(service.price_label, price)
            self.assertEqual(service.duration_minutes, minutes)
            self.assertTrue(service.staff_members.filter(pk=self.doctor.pk).exists())
        call_command("seed_booking", stdout=StringIO())
        self.assertTrue(Service.objects.get(slug="skinbooster").active)
        self.assertTrue(Service.objects.get(slug="skinbooster").bookable)
