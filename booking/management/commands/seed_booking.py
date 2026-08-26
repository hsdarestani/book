from datetime import time
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from booking.models import Service, StaffMember, WorkingHour


class Command(BaseCommand):
    help = 'Legt eine sichere Grundkonfiguration für das Buchungssystem an.'

    def handle(self, *args, **options):
        service_specs = [
            ('Beratung', 30, ''),
            ('Botulinumtoxin', 30, ''),
            ('Hyaluronsäure', 45, ''),
            ('Skinbooster', 45, ''),
            ('Laserbehandlung', 45, ''),
        ]
        services = []
        for order, (name, duration, price) in enumerate(service_specs, start=10):
            service, _ = Service.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    'name': name,
                    'duration_minutes': duration,
                    'buffer_minutes': 10,
                    'price_label': price,
                    'sort_order': order,
                },
            )
            services.append(service)

        staff, _ = StaffMember.objects.get_or_create(
            display_name='A+esthetic Team',
            defaults={'role': 'team', 'sort_order': 10},
        )
        staff.services.set(services)
        for weekday in range(5):
            WorkingHour.objects.get_or_create(
                staff=staff,
                weekday=weekday,
                start_time=time(9, 0),
                defaults={'end_time': time(18, 0), 'active': True},
            )
        self.stdout.write(self.style.SUCCESS('Grundkonfiguration ist vorhanden.'))
