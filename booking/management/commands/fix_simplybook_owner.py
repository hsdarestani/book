from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from booking.models import Appointment, DailyAvailabilityOverride, Service, StaffMember


class Command(BaseCommand):
    help = 'Assigns every SimplyBook-imported record to Frau Ariane Regaei and removes artificial SimplyBook staff records.'

    @transaction.atomic
    def handle(self, *args, **options):
        ariane = StaffMember.objects.filter(display_name='Frau Ariane Regaei').order_by('pk').first()
        if ariane is None:
            raise CommandError('Frau Ariane Regaei was not found; refusing to change SimplyBook ownership.')

        appointments = Appointment.objects.filter(idempotency_key__startswith='simplybook-')
        appointment_count = appointments.exclude(staff=ariane).count()
        appointments.update(staff=ariane)

        imported_services = list(Service.objects.filter(slug__startswith='simplybook-event-'))
        if imported_services:
            ariane.services.add(*imported_services)

        archives = list(StaffMember.objects.filter(display_name__startswith='A+ Esthetic (SimplyBook #'))
        override_count = 0
        for archive in archives:
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
                override_count += 1

        DailyAvailabilityOverride.objects.filter(staff__in=archives).delete()
        archive_count = len(archives)
        if archives:
            StaffMember.objects.filter(pk__in=[staff.pk for staff in archives]).delete()

        self.stdout.write(self.style.SUCCESS(
            'SimplyBook ownership fixed: '
            f'{appointment_count} appointments reassigned, '
            f'{override_count} daily schedules moved, '
            f'{archive_count} artificial staff records removed.'
        ))
