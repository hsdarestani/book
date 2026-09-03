import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def _public_base_url():
    return getattr(settings, 'BOOKING_PUBLIC_BASE_URL', 'https://book.a-esthetic.de').rstrip('/')


def _staff_image_url(appointment):
    base_url = _public_base_url()
    if appointment.staff.photo:
        try:
            photo_url = appointment.staff.photo.url
            if photo_url.startswith(('http://', 'https://')):
                return photo_url
            return f'{base_url}{photo_url}'
        except ValueError:
            pass

    name = appointment.staff.display_name.lower()
    filename = 'ariane-regaei.jpg' if 'ariane' in name else 'doctor-male.jpg'
    return f'{base_url}/static/booking/staff/{filename}'


def _send_html_mail(subject, text_body, html_body, recipients):
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)


def send_booking_emails(appointment):
    local_start = timezone.localtime(appointment.starts_at)
    base_url = _public_base_url()
    common_context = {
        'appointment': appointment,
        'local_start': local_start,
        'logo_url': f'{base_url}/static/booking/logo.png',
        'staff_image_url': _staff_image_url(appointment),
        'website_url': 'https://a-esthetic.de',
        'admin_url': f'{base_url}/verwaltung/#termine',
    }

    subject = 'Deine Terminbestätigung bei A+Esthetic'
    customer_text = (
        f'Hallo {appointment.customer.first_name},\n\n'
        'dein Termin wurde gespeichert.\n\n'
        f'Behandlung: {appointment.service.name}\n'
        f'Datum: {local_start:%d.%m.%Y}\n'
        f'Uhrzeit: {local_start:%H:%M}\n'
        f'Behandler: {appointment.staff.display_name}\n'
        f'Status: {appointment.get_status_display()}\n'
        f'Preis: {appointment.service.price_label or "nach Beratung"}\n\n'
        'Wenn du Fragen hast, melde dich bitte direkt bei A+Esthetic.\n\n'
        'A+Esthetic'
    )
    customer_html = render_to_string(
        'booking/email_booking_confirmation.html',
        {**common_context, 'is_admin': False},
    )

    try:
        _send_html_mail(subject, customer_text, customer_html, [appointment.customer.email])

        if settings.BOOKING_NOTIFICATION_EMAIL:
            admin_subject = f'Neuer Termin: {appointment.service.name}'
            admin_text = (
                f'{appointment.customer.full_name}\n'
                f'{appointment.customer.email}\n'
                f'{appointment.customer.phone}\n\n'
                f'{appointment.service.name}\n'
                f'{local_start:%d.%m.%Y %H:%M}\n'
                f'{appointment.staff.display_name}\n'
                f'Status: {appointment.get_status_display()}'
            )
            admin_html = render_to_string(
                'booking/email_booking_confirmation.html',
                {**common_context, 'is_admin': True},
            )
            _send_html_mail(
                admin_subject,
                admin_text,
                admin_html,
                [settings.BOOKING_NOTIFICATION_EMAIL],
            )
    except Exception:
        logger.exception('Termin-E-Mail konnte nicht versendet werden')
