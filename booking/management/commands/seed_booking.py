from datetime import time

from django.core.management.base import BaseCommand
from booking.models import Service, StaffMember, WorkingHour


class Command(BaseCommand):
    help = 'Legt eine sichere Grundkonfiguration für das Buchungssystem an, ohne Admin-Einstellungen bei jedem Deploy zu überschreiben.'

    def handle(self, *args, **options):
        service_specs = [
            ('Ästhetische Erstberatung', 'aesthetische-erstberatung', 30, 10, 'Individuelle Beratung', True),
            ('Botox Beratung', 'botox-beratung', 30, 10, 'ab 119 €', True),
            ('Hyaluron Beratung', 'hyaluron-beratung', 30, 10, 'ab 200 €', True),
            ('Laser-Haarentfernung', 'laser-haarentfernung', 45, 10, 'je nach Areal', False),
            ('RF-Microneedling', 'rf-microneedling', 60, 15, 'Preis nach Region', False),
            ('PRP Beratung', 'prp-beratung', 30, 10, 'Preis nach Beratung', True),
            ('Skinbooster Beratung', 'skinbooster-beratung', 30, 10, 'Preis nach Beratung', True),
            ('Infusionstherapie', 'infusionstherapie', 60, 10, 'ab 119 €', True),
            ('Injektionslipolyse Beratung', 'injektionslipolyse-beratung', 30, 10, 'ab 149 €', True),
        ]

        services = []
        for order, (name, slug, duration, buffer, price, requires_confirmation) in enumerate(service_specs, start=10):
            service, created = Service.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': 'Terminanfrage bei A+esthetic. Beratung, Aufklärung und Bestätigung erfolgen persönlich durch das A+esthetic Team.',
                    'duration_minutes': duration,
                    'buffer_minutes': buffer,
                    'price_label': price,
                    'active': True,
                    'bookable': True,
                    'requires_confirmation': requires_confirmation,
                    'sort_order': order,
                },
            )
            services.append(service)

        Service.objects.filter(
            slug__in=['beratung', 'botulinumtoxin', 'hyaluronsaure', 'skinbooster', 'laserbehandlung']
        ).update(active=False, bookable=False)

        # The provider records are seeded by migration 0003. If a fresh/manual database
        # is missing them, create safe defaults once. Existing provider settings, service
        # assignments and working hours are deliberately not reset on future deploys.
        if not StaffMember.objects.filter(role='doctor').exists():
            for sort_order, name in [(10, 'Frau Ariane Regaei'), (20, 'A+esthetic Arzt')]:
                provider = StaffMember.objects.create(
                    display_name=name,
                    role='doctor',
                    active=True,
                    sort_order=sort_order,
                )
                provider.services.set(services)
                for weekday in range(5):
                    WorkingHour.objects.create(
                        staff=provider,
                        weekday=weekday,
                        start_time=time(10, 0),
                        end_time=time(18, 0),
                        active=True,
                    )

        if StaffMember.objects.filter(role='doctor', active=True).exists():
            StaffMember.objects.filter(display_name='A+esthetic Team').update(active=False)

        self.stdout.write(self.style.SUCCESS('Grundkonfiguration ist vorhanden.'))
