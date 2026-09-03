from django.core.management.base import BaseCommand, CommandError

from booking.emails import send_customer_booking_email
from booking.models import Appointment


class Command(BaseCommand):
    help = 'Resend the latest customer booking confirmation for a matching customer.'

    def add_arguments(self, parser):
        parser.add_argument('--first-name', required=True)
        parser.add_argument('--last-name', required=True)
        parser.add_argument('--email')

    def handle(self, *args, **options):
        appointments = (
            Appointment.objects.select_related('customer', 'service', 'staff')
            .filter(
                customer__first_name__iexact=options['first_name'].strip(),
                customer__last_name__iexact=options['last_name'].strip(),
            )
            .order_by('-created_at')
        )
        if options.get('email'):
            appointments = appointments.filter(customer__email__iexact=options['email'].strip())

        appointment = appointments.first()
        if not appointment:
            raise CommandError('Kein passender Termin gefunden.')

        send_customer_booking_email(appointment)
        self.stdout.write(
            self.style.SUCCESS(
                f'Kunden-E-Mail erneut gesendet: {appointment.customer.email} | '
                f'{appointment.service.name} | {appointment.starts_at:%d.%m.%Y %H:%M}'
            )
        )
