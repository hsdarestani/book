import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


CLINIC_ADDRESS = 'Stiftstraße 14, 60313 Frankfurt am Main · 2. OG'
CLINIC_PHONE = '069 71417012'
CLINIC_PHONE_HREF = 'tel:+496971417012'
WHATSAPP_URL = 'https://wa.me/496971417012'
INSTAGRAM_URL = 'https://www.instagram.com/aplus.esthetic/'
DIRECTIONS_URL = 'https://www.google.com/maps/dir/?api=1&destination=Stiftstra%C3%9Fe+14%2C+60313+Frankfurt+am+Main'
GOOGLE_REVIEWS_URL = 'https://www.google.com/maps/search/?api=1&query=A%2B+Esthetic%2C+Stiftstra%C3%9Fe+14%2C+60313+Frankfurt+am+Main'
EMAIL_HERO_IMAGE_URL = 'https://a-esthetic.de/wp-content/uploads/prev.png'


def _public_base_url():
    return getattr(settings, 'BOOKING_PUBLIC_BASE_URL', 'https://book.a-esthetic.de').rstrip('/')


def _staff_image_url(appointment):
    return EMAIL_HERO_IMAGE_URL


def _email_staff_name(staff):
    name = (staff.display_name or '').strip()
    parts = name.split()
    if len(parts) >= 3 and parts[0] in {'Frau', 'Herr'}:
        return f'{parts[0]} {parts[1][0]}. {" ".join(parts[2:])}'
    if len(parts) >= 2:
        return f'{parts[0][0]}. {" ".join(parts[1:])}'
    return name


def _send_html_mail(subject, text_body, html_body, recipients):
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)


def _booking_email_context(appointment):
    local_start = timezone.localtime(appointment.starts_at)
    base_url = _public_base_url()
    return {
        'appointment': appointment,
        'local_start': local_start,
        'staff_email_name': _email_staff_name(appointment.staff),
        'staff_image_url': _staff_image_url(appointment),
        'website_url': 'https://a-esthetic.de',
        'admin_url': f'{base_url}/verwaltung/#termine',
        'calendar_url': f'{base_url}/termin/{appointment.public_id}/kalender.ics',
        'directions_url': DIRECTIONS_URL,
        'instagram_url': INSTAGRAM_URL,
        'google_reviews_url': GOOGLE_REVIEWS_URL,
        'whatsapp_url': WHATSAPP_URL,
        'clinic_address': CLINIC_ADDRESS,
        'clinic_phone': CLINIC_PHONE,
        'clinic_phone_href': CLINIC_PHONE_HREF,
    }


def send_customer_booking_email(appointment):
    context = _booking_email_context(appointment)
    local_start = context['local_start']
    staff_email_name = context['staff_email_name']
    calendar_url = context['calendar_url']

    subject = 'Deine Terminbestätigung bei A+ Esthetic'
    customer_text = (
        f'Hallo {appointment.customer.first_name},\n'
        'hier findest du alle wichtigen Informationen zu deinem Termin auf einen Blick.\n\n'
        f'Behandlung: {appointment.service.name}\n'
        f'Datum: {local_start:%d.%m.%Y}\n'
        f'Uhrzeit: {local_start:%H:%M}\n'
        f'Behandelnde/r Arzt/Ärztin: {staff_email_name}\n\n'
        'Kontaktdaten:\n'
        f'A+ Esthetic Frankfurt · {CLINIC_ADDRESS}\n'
        f'Telefon: {CLINIC_PHONE}\n\n'
        f'Zum Kalender hinzufügen: {calendar_url}\n'
        f'Wegbeschreibung: {DIRECTIONS_URL}\n'
        f'Instagram: {INSTAGRAM_URL}\n'
        f'Google Bewertungen: {GOOGLE_REVIEWS_URL}\n'
        f'WhatsApp: {WHATSAPP_URL}\n\n'
        'Wenn du Fragen hast, melde dich bitte direkt bei A+Esthetic.\n\n'
        'A+Esthetic'
    )
    customer_html = render_to_string(
        'booking/email_booking_confirmation.html',
        {**context, 'is_admin': False},
    )
    _send_html_mail(subject, customer_text, customer_html, [appointment.customer.email])


def send_booking_emails(appointment):
    context = _booking_email_context(appointment)
    local_start = context['local_start']

    try:
        send_customer_booking_email(appointment)

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
                {**context, 'is_admin': True},
            )
            _send_html_mail(
                admin_subject,
                admin_text,
                admin_html,
                [settings.BOOKING_NOTIFICATION_EMAIL],
            )
    except Exception:
        logger.exception('Termin-E-Mail konnte nicht versendet werden')
