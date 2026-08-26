from datetime import time
from django.db import migrations


def align_catalog(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    StaffMember = apps.get_model('booking', 'StaffMember')
    WorkingHour = apps.get_model('booking', 'WorkingHour')

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
        service, _ = Service.objects.update_or_create(
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

    legacy_slugs = ['beratung', 'botulinumtoxin', 'hyaluronsaure', 'skinbooster', 'laserbehandlung']
    Service.objects.filter(slug__in=legacy_slugs).update(active=False, bookable=False)

    staff = StaffMember.objects.filter(display_name='A+esthetic Team').order_by('pk').first()
    if not staff:
        staff = StaffMember.objects.create(display_name='A+esthetic Team', role='specialist', active=True, sort_order=10)
    staff.role = 'specialist'
    staff.active = True
    staff.sort_order = 10
    staff.save(update_fields=['role', 'active', 'sort_order'])
    staff.services.set(services)

    WorkingHour.objects.filter(staff=staff).delete()
    for weekday in range(5):
        WorkingHour.objects.create(
            staff=staff,
            weekday=weekday,
            start_time=time(10, 0),
            end_time=time(18, 0),
            active=True,
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('booking', '0001_initial')]
    operations = [migrations.RunPython(align_catalog, noop_reverse)]
