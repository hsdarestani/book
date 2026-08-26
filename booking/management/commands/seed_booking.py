from datetime import time
from django.core.management.base import BaseCommand
from booking.models import Service, StaffMember, WorkingHour


class Command(BaseCommand):
    help = 'Legt nur bei einer vollständig leeren Datenbank eine sichere Grundkonfiguration an.'

    def handle(self, *args, **options):
        if Service.objects.exists() and StaffMember.objects.exists():
            self.stdout.write(self.style.SUCCESS('Grundkonfiguration ist vorhanden.'))
            return

        definitions = [
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
        for order, (name, slug, duration, buffer, price, requires_confirmation) in enumerate(definitions, start=10):
            service, _ = Service.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': 'Terminanfrage bei A+esthetic. Beratung, Aufklärung und Bestätigung erfolgen persönlich durch das A+esthetic Team.',
                    'duration_minutes': duration,
                    'buffer_minutes': buffer,
                    'price_label': price,
                    'requires_confirmation': requires_confirmation,
                    'sort_order': order,
                },
            )
            services.append(service)

        staff, _ = StaffMember.objects.get_or_create(
            display_name='A+esthetic Team',
            defaults={'role': 'specialist', 'sort_order': 10},
        )
        staff.services.set(services)
        for weekday in range(5):
            WorkingHour.objects.get_or_create(
                staff=staff,
                weekday=weekday,
                start_time=time(10, 0),
                defaults={'end_time': time(18, 0), 'active': True},
            )
        self.stdout.write(self.style.SUCCESS('Grundkonfiguration wurde angelegt.'))
