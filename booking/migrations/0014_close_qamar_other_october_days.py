from datetime import date

from django.db import migrations


ALLOWED_DAYS = {2, 3, 4, 12, 13, 14, 19, 20, 21, 24, 25, 26, 27}


def close_other_october_days(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')

    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if not qamar:
        return

    for day in range(1, 32):
        if day in ALLOWED_DAYS:
            continue
        Override.objects.update_or_create(
            staff=qamar,
            date=date(2026, 10, day),
            defaults={
                'closed': True,
                'start_time_1': None,
                'end_time_1': None,
                'start_time_2': None,
                'end_time_2': None,
            },
        )


def reopen_other_october_days(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')

    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if not qamar:
        return

    Override.objects.filter(
        staff=qamar,
        date__year=2026,
        date__month=10,
    ).exclude(date__day__in=sorted(ALLOWED_DAYS)).delete()


class Migration(migrations.Migration):
    dependencies = [('booking', '0013_points_dashboard_whatsapp_view_only')]

    operations = [
        migrations.RunPython(close_other_october_days, reopen_other_october_days),
    ]
