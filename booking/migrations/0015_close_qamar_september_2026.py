from datetime import date

from django.db import migrations


def close_qamar_september_2026(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')

    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if not qamar:
        return

    for day in range(1, 31):
        Override.objects.update_or_create(
            staff=qamar,
            date=date(2026, 9, day),
            defaults={
                'closed': True,
                'start_time_1': None,
                'end_time_1': None,
                'start_time_2': None,
                'end_time_2': None,
            },
        )


def reopen_qamar_september_2026(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')

    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if not qamar:
        return

    Override.objects.filter(
        staff=qamar,
        date__year=2026,
        date__month=9,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('booking', '0014_close_qamar_other_october_days')]

    operations = [
        migrations.RunPython(close_qamar_september_2026, reopen_qamar_september_2026),
    ]
