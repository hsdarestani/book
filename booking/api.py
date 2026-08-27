import json
from datetime import timedelta

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST

from .emails import send_booking_emails
from .models import Customer, Service, StaffMember
from .services import BOOKING_HORIZON_DAYS, available_slots, create_appointment


def _json(request):
    try:
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _error(code, message, status=400):
    return JsonResponse({'ok': False, 'error': code, 'message': message}, status=status)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'ja', 'on'}


@require_GET
def health(request):
    return JsonResponse({'ok': True, 'service': 'A+esthetic Buchung', 'time': timezone.now().isoformat()})


@require_GET
def services(request):
    items = Service.objects.filter(active=True, bookable=True).order_by('sort_order', 'name')
    return JsonResponse({'ok': True, 'services': [
        {
            'id': item.pk,
            'name': item.name,
            'slug': item.slug,
            'description': item.description,
            'duration_minutes': item.duration_minutes,
            'price_label': item.price_label,
        }
        for item in items
    ]})


@require_GET
def staff(request):
    service_id = request.GET.get('service_id')
    if not service_id:
        return _error('service_required', 'Bitte wähle zuerst eine Behandlung.')
    service = Service.objects.filter(pk=service_id, active=True, bookable=True).first()
    if not service:
        return _error('service_not_found', 'Die gewählte Behandlung ist nicht verfügbar.', 404)
    items = StaffMember.objects.filter(active=True, services=service).distinct().order_by('sort_order', 'display_name')
    return JsonResponse({'ok': True, 'staff': [
        {
            'id': item.pk,
            'name': item.display_name,
            'role': item.get_role_display(),
            'bio': item.bio,
            'photo_url': item.photo.url if item.photo else '',
        }
        for item in items
    ]})


@require_GET
def availability(request):
    service_id = request.GET.get('service_id')
    staff_id = request.GET.get('staff_id')
    day = parse_date(request.GET.get('date', ''))
    if not service_id or not staff_id or not day:
        return _error('invalid_request', 'Behandlung, Behandler und Datum sind erforderlich.')
    if day < timezone.localdate() or day > timezone.localdate() + timedelta(days=BOOKING_HORIZON_DAYS):
        return _error('date_out_of_range', 'Dieses Datum liegt außerhalb des Buchungszeitraums.')
    service = Service.objects.filter(pk=service_id, active=True, bookable=True).first()
    member = StaffMember.objects.filter(pk=staff_id, active=True, services=service).first() if service else None
    if not service or not member:
        return _error('not_available', 'Die gewählte Kombination ist nicht verfügbar.', 404)
    slots = available_slots(service, member, day)
    return JsonResponse({'ok': True, 'slots': [
        {'starts_at': slot.isoformat(), 'label': timezone.localtime(slot).strftime('%H:%M')}
        for slot in slots
    ]})


@require_GET
def availability_overview(request):
    service_id = request.GET.get('service_id')
    staff_id = request.GET.get('staff_id')
    try:
        days = max(7, min(int(request.GET.get('days', '30')), BOOKING_HORIZON_DAYS + 1))
    except ValueError:
        days = 30
    if not service_id or not staff_id:
        return _error('invalid_request', 'Behandlung und Behandler sind erforderlich.')
    service = Service.objects.filter(pk=service_id, active=True, bookable=True).first()
    member = StaffMember.objects.filter(pk=staff_id, active=True, services=service).first() if service else None
    if not service or not member:
        return _error('not_available', 'Die gewählte Kombination ist nicht verfügbar.', 404)

    today = timezone.localdate()
    groups = []
    for offset in range(days):
        day = today + timedelta(days=offset)
        slots = available_slots(service, member, day)
        if not slots:
            continue
        groups.append({
            'date': day.isoformat(),
            'weekday': day.strftime('%A'),
            'date_label': day.strftime('%d.%m.%Y'),
            'slots': [
                {'starts_at': slot.isoformat(), 'label': timezone.localtime(slot).strftime('%H:%M')}
                for slot in slots
            ],
        })
    return JsonResponse({'ok': True, 'days': groups, 'range_days': days})


@require_POST
def appointments(request):
    data = _json(request)
    required = ['service_id', 'staff_id', 'starts_at', 'first_name', 'last_name', 'email', 'phone', 'referral_source']
    if any(not str(data.get(key) or '').strip() for key in required):
        return _error('missing_fields', 'Bitte fülle alle Pflichtfelder aus.')
    if not _as_bool(data.get('cancellation_terms_accepted')):
        return _error('cancellation_terms_required', 'Bitte bestätige die Stornierungsbedingungen.')
    if not _as_bool(data.get('privacy_accepted')):
        return _error('privacy_required', 'Bitte bestätige die Datenschutzhinweise.')

    service = Service.objects.filter(pk=data.get('service_id'), active=True, bookable=True).first()
    member = StaffMember.objects.filter(pk=data.get('staff_id'), active=True).first()
    starts_at = parse_datetime(str(data.get('starts_at') or ''))
    if not service or not member or not member.services.filter(pk=service.pk).exists():
        return _error('not_available', 'Die gewählte Behandlung ist nicht verfügbar.', 404)
    if not starts_at:
        return _error('invalid_start', 'Die gewählte Uhrzeit ist ungültig.')
    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())

    email = str(data.get('email') or '').strip().lower()
    if '@' not in email:
        return _error('invalid_email', 'Bitte gib eine gültige E-Mail-Adresse ein.')

    idempotency_key = (request.headers.get('Idempotency-Key') or str(data.get('idempotency_key') or '')).strip()[:80] or None
    if idempotency_key:
        from .models import Appointment
        existing = Appointment.objects.select_related('customer', 'service', 'staff').filter(idempotency_key=idempotency_key).first()
        if existing:
            return JsonResponse({
                'ok': True,
                'created': False,
                'appointment': {
                    'id': str(existing.public_id),
                    'status': existing.status,
                    'status_label': existing.get_status_display(),
                },
            })

    with transaction.atomic():
        customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
        if customer:
            customer.first_name = str(data.get('first_name')).strip()[:80]
            customer.last_name = str(data.get('last_name')).strip()[:80]
            customer.phone = str(data.get('phone')).strip()[:40]
            customer.save(update_fields=['first_name', 'last_name', 'phone', 'updated_at'])
        else:
            customer = Customer.objects.create(
                first_name=str(data.get('first_name')).strip()[:80],
                last_name=str(data.get('last_name')).strip()[:80],
                phone=str(data.get('phone')).strip()[:40],
                email=email,
            )
        try:
            appointment, created = create_appointment(
                customer=customer,
                service=service,
                staff=member,
                starts_at=starts_at,
                idempotency_key=idempotency_key,
                source='web',
                returning_customer=_as_bool(data.get('returning_customer')),
                referral_source=str(data.get('referral_source') or '').strip(),
                marketing_opt_in=_as_bool(data.get('marketing_opt_in'), default=True),
                cancellation_terms_accepted=True,
                privacy_accepted=True,
            )
        except ValueError:
            return _error('time_not_available', 'Dieser Termin ist inzwischen nicht mehr verfügbar.', 409)
        if created:
            transaction.on_commit(lambda: send_booking_emails(appointment))

    return JsonResponse({
        'ok': True,
        'created': created,
        'message': 'Dein Termin wurde erfolgreich gespeichert.',
        'appointment': {
            'id': str(appointment.public_id),
            'status': appointment.status,
            'status_label': appointment.get_status_display(),
            'service': appointment.service.name,
            'staff': appointment.staff.display_name,
            'starts_at': appointment.starts_at.isoformat(),
        },
    }, status=201 if created else 200)
