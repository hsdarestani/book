"""Explicit, reviewable recovery of PRP and Skinbooster online booking.

Read-only by default. Requires confirmed website prices, clinician-selected
durations, and explicit active doctor IDs before changing production data.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from booking.models import Service, StaffMember


CATALOG = (
    ("prp-behandlung", "PRP-Behandlung", "ab 350 €", 65),
    ("skinbooster", "Skinbooster", "ab 250 €", 70),
)


class Command(BaseCommand):
    help = "Audit or explicitly restore PRP/Skinbooster catalog entries and clinician assignments."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes after clinic verification.")
        parser.add_argument("--confirm-prices", action="store_true",
                            help="Clinic has confirmed the published PRP 350 EUR / Skinbooster 250 EUR starting prices.")
        parser.add_argument("--prp-minutes", type=int, help="Clinician-approved PRP booking duration.")
        parser.add_argument("--skinbooster-minutes", type=int, help="Clinician-approved Skinbooster booking duration.")
        parser.add_argument("--doctor-id", action="append", type=int, dest="doctor_ids",
                            help="Clinician authorized for BOTH treatments; repeat for each doctor.")

    def handle(self, *args, **options):
        for slug, label, website_price, _ in CATALOG:
            service = Service.objects.filter(slug=slug).first()
            if service:
                assigned = list(service.staff_members.filter(active=True, role="doctor")
                                .values_list("pk", "display_name"))
                self.stdout.write(
                    f"{slug}: id={service.pk}, active={service.active}, "
                    f"bookable={service.bookable}, price={service.price_label!r}, "
                    f"duration={service.duration_minutes}, doctors={assigned}"
                )
            else:
                self.stdout.write(f"{slug}: MISSING (published price: {website_price})")

        if not options["apply"]:
            self.stdout.write("DRY RUN: no data changed. Clinic approval required for --apply.")
            return

        if not options["confirm_prices"]:
            raise CommandError("Confirm both published prices with the clinic before --apply.")
        durations = {
            "prp-behandlung": options["prp_minutes"],
            "skinbooster": options["skinbooster_minutes"],
        }
        if any(value is None or not 5 <= value <= 240 for value in durations.values()):
            raise CommandError("Both clinician-approved durations (5-240 min) are required.")
        ids = set(options["doctor_ids"] or [])
        if not ids:
            raise CommandError("Specify at least one clinician-approved --doctor-id.")
        doctors = list(StaffMember.objects.filter(pk__in=ids, active=True, role="doctor"))
        if {doctor.pk for doctor in doctors} != ids:
            raise CommandError("Each --doctor-id must identify an active doctor.")

        with transaction.atomic():
            for slug, name, price, sort_order in CATALOG:
                service, created = Service.objects.get_or_create(
                    slug=slug,
                    defaults={
                        "name": name,
                        "description": "Medizinische Behandlung nach individueller Aufklärung; "
                                       "Terminbestätigung durch das Praxisteam.",
                        "duration_minutes": durations[slug],
                        "buffer_minutes": 10,
                        "price_label": price,
                        "active": True,
                        "bookable": True,
                        "requires_confirmation": True,
                        "sort_order": sort_order,
                    },
                )
                if not created:
                    service.name = name
                    service.price_label = price
                    service.duration_minutes = durations[slug]
                    service.active = True
                    service.bookable = True
                    service.requires_confirmation = True
                    service.save(update_fields=[
                        "name", "price_label", "duration_minutes", "active",
                        "bookable", "requires_confirmation",
                    ])
                service.staff_members.add(*doctors)
                self.stdout.write(
                    f"Restored {name} (id={service.pk}); manual confirmation required; "
                    f"assigned doctors={[doctor.pk for doctor in doctors]}"
                )
        self.stdout.write(self.style.SUCCESS("Catalog restored; verify /api/services, staff and availability."))
