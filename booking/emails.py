import logging
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_booking_emails(appointment):
    local_start = timezone.localtime(appointment.starts_at)
    subject = 'Deine Terminbestätigung bei A+Esthetic'
    customer_text = (
        f'Hallo {appointment.customer.first_name},\n\n'
        f'dein Termin wurde gespeichert.\n\n'
        f'Behandlung: {appointment.service.name}\n'
        f'Datum: {local_start:%d.%m.%Y}\n'
        f'Uhrzeit: {local_start:%H:%M}\n'
        f'Behandler: {appointment.staff.display_name}\n'
        f'Status: {appointment.get_status_display()}\n\n'
        'Wenn du Fragen hast, melde dich bitte direkt bei A+Esthetic.\n\n'
        'A+Esthetic'
    )
    try:
        send_mail(subject, customer_text, settings.DEFAULT_FROM_EMAIL, [appointment.customer.email], fail_silently=False)
        if settings.BOOKING_NOTIFICATION_EMAIL:
            send_mail(
                f'Neuer Termin: {appointment.service.name}',
                f'{appointment.customer.full_name} – {local_start:%d.%m.%Y %H:%M} – {appointment.staff.display_name}',
                settings.DEFAULT_FROM_EMAIL,
                [settings.BOOKING_NOTIFICATION_EMAIL],
                fail_silently=False,
            )
    except Exception:
        logger.exception('Termin-E-Mail konnte nicht versendet werden')
