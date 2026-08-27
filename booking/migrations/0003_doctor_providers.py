from datetime import time

from django.db import migrations


def add_doctor_providers(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    StaffMember = apps.get_model('booking', 'StaffMember')
    WorkingHour = apps.get_model('booking', 'WorkingHour')

    services = list(Service.objects.filter(active=True, bookable=True).order_by('sort_order', 'name'))
    team = StaffMember.objects.filter(display_name='A+esthetic Team').order_by('pk').first()
    template_hours = []
    if team:
        template_hours = list(
            WorkingHour.objects.filter(staff=team, active=True)
            .order_by('weekday', 'start_time')
            .values('weekday', 'start_time', 'end_time', 'active')
        )
    if not template_hours:
        template_hours = [
            {'weekday': weekday, 'start_time': time(10, 0), 'end_time': time(18, 0), 'active': True}
            for weekday in range(5)
        ]

    providers = [
        ('Frau Ariane Regaei', 10),
        ('A+esthetic Arzt', 20),
    ]
    for name, sort_order in providers:
        provider, _ = StaffMember.objects.update_or_create(
            display_name=name,
            defaults={
                'role': 'doctor',
                'active': True,
                'sort_order': sort_order,
            },
        )
        provider.services.set(services)
        WorkingHour.objects.filter(staff=provider).delete()
        for item in template_hours:
            WorkingHour.objects.create(
                staff=provider,
                weekday=item['weekday'],
                start_time=item['start_time'],
                end_time=item['end_time'],
                active=item['active'],
            )

    if team:
        team.active = False
        team.save(update_fields=['active'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('booking', '0002_canonical_aesthetic_catalog')]
    operations = [migrations.RunPython(add_doctor_providers, noop_reverse)]
