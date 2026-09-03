from django.db import migrations


def reassign_simplybook_to_ariane(apps, schema_editor):
    StaffMember = apps.get_model('booking', 'StaffMember')
    Appointment = apps.get_model('booking', 'Appointment')
    DailyAvailabilityOverride = apps.get_model('booking', 'DailyAvailabilityOverride')
    Service = apps.get_model('booking', 'Service')

    ariane = StaffMember.objects.filter(display_name='Frau Ariane Regaei').order_by('pk').first()
    if ariane is None:
        raise RuntimeError('Cannot repair SimplyBook import: Frau Ariane Regaei was not found.')

    # Every booking imported from SimplyBook belongs to Ariane.
    Appointment.objects.filter(idempotency_key__startswith='simplybook-').update(staff=ariane)

    # Imported historical services belong to Ariane as well. Keep Ariane's existing
    # service assignments and add the archived SimplyBook catalog alongside them.
    imported_services = list(Service.objects.filter(slug__startswith='simplybook-event-'))
    if imported_services:
        ariane.services.add(*imported_services)

    # The first importer created one or more artificial archive staff records.
    # Move their dated work-calendar overrides to Ariane, then remove those records.
    archive_staff = list(StaffMember.objects.filter(display_name__startswith='A+ Esthetic (SimplyBook #'))
    for archive in archive_staff:
        for source in DailyAvailabilityOverride.objects.filter(staff=archive).order_by('date'):
            DailyAvailabilityOverride.objects.update_or_create(
                staff=ariane,
                date=source.date,
                defaults={
                    'closed': source.closed,
                    'start_time_1': source.start_time_1,
                    'end_time_1': source.end_time_1,
                    'start_time_2': source.start_time_2,
                    'end_time_2': source.end_time_2,
                },
            )

    DailyAvailabilityOverride.objects.filter(staff__in=archive_staff).delete()
    if archive_staff:
        StaffMember.objects.filter(pk__in=[staff.pk for staff in archive_staff]).delete()


def noop_reverse(apps, schema_editor):
    # This migration corrects an erroneous provider assignment. Reversing it would
    # recreate incorrect production data, so intentionally keep the repaired state.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0010_dailyavailabilityoverride'),
    ]

    operations = [
        migrations.RunPython(reassign_simplybook_to_ariane, noop_reverse),
    ]
