from datetime import timezone as dt_timezone

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Appointment


CLINIC_LOCATION = 'A+Esthetic, Stiftstraße 14, 60313 Frankfurt am Main, 2. OG'


def _ics_escape(value):
    return (
        str(value or '')
        .replace('\\', '\\\\')
        .replace('\r\n', '\\n')
        .replace('\n', '\\n')
        .replace(';', '\\;')
        .replace(',', '\\,')
    )


def _ics_utc(value):
    return value.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


@require_GET
def appointment_calendar(request, appointment_id):
    appointment = get_object_or_404(
        Appointment.objects.select_related('service'),
        public_id=appointment_id,
    )
    now = timezone.now()
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//A+Esthetic//Terminbuchung//DE',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:{appointment.public_id}@book.a-esthetic.de',
        f'DTSTAMP:{_ics_utc(now)}',
        f'DTSTART:{_ics_utc(appointment.starts_at)}',
        f'DTEND:{_ics_utc(appointment.ends_at)}',
        f'SUMMARY:{_ics_escape("A+Esthetic – " + appointment.service.name)}',
        f'LOCATION:{_ics_escape(CLINIC_LOCATION)}',
        'DESCRIPTION:Termin bei A+Esthetic Frankfurt. Telefon: 069 71417012',
        'URL:https://a-esthetic.de',
        'END:VEVENT',
        'END:VCALENDAR',
        '',
    ]
    response = HttpResponse('\r\n'.join(lines), content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="aesthetic-termin.ics"'
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response
