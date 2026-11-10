import hashlib
import json
import logging
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .emails import send_booking_emails
from .customer_identity import normalize_name, normalize_phone, resolve_app_booking_identity
from .models import Appointment, Customer, Service, StaffMember
from .notifications import notify_booking_created, notify_customer_cancelled, notify_customer_rescheduled
from .demo_booking_guard import is_blocked_demo_customer, blocked_demo_response, log_blocked_demo_booking
from .package_bridge import sync_package
from .services import BOOKING_HORIZON_DAYS, LEAD_TIME, available_slots, create_appointment

CHANGE_DEADLINE_HOURS = max(1, int(getattr(settings, 'BOOKING_CHANGE_DEADLINE_HOURS', 24)))
logger = logging.getLogger(__name__)


def _json(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _error(code, message, status=400):
    return JsonResponse({'ok': False, 'error': code, 'message': message}, status=status)


def _member(request):
    authorization = request.headers.get('Authorization', '').strip()
    if not authorization.startswith('Bearer '):
        return None, _error('authentication_required', 'Bitte melden Sie sich erneut an.', 401)

    upstream = Request(
        settings.AESTHETIC_MEMBER_API_URL,
        method='GET',
        headers={
            'Authorization': authorization,
            'Accept': 'application/json',
            'User-Agent': 'Aesthetic-Booking/1.0',
        },
    )
    try:
        with urlopen(upstream, timeout=8) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 401:
            return None, _error('authentication_required', 'Bitte melden Sie sich erneut an.', 401)
        return None, _error('identity_service_unavailable', 'Die Anmeldung konnte gerade nicht geprüft werden.', 503)
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None, _error('identity_service_unavailable', 'Die Anmeldung konnte gerade nicht geprüft werden.', 503)

    if not payload.get('ok'):
        return None, _error('authentication_required', 'Bitte melden Sie sich erneut an.', 401)

    profile = payload.get('profile') or {}
    member = payload.get('member') or {}
    email = str(profile.get('email') or '').strip().lower()
    if not email or '@' not in email:
        return None, _error('valid_email_required', 'Für die Terminbuchung ist eine gültige E-Mail-Adresse erforderlich.', 400)

    # The profile has verified first/last fields. Never synthesize a patient
    # name from the username or email local-part: that causes false conflicts
    # against legacy SimplyBook patient records.
    first_name = str(profile.get('first_name') or '').strip()[:80]
    last_name = str(profile.get('last_name') or '').strip()[:80]
    if not first_name or not last_name:
        display_name = str(member.get('name') or '').strip()
        if display_name.casefold() not in (email.casefold(), email.split('@', 1)[0].casefold()):
            parts = display_name.split()
            if len(parts) >= 2:
                first_name = first_name or ' '.join(parts[:-1])[:80]
                last_name = last_name or parts[-1][:80]

    return {
        'email': email,
        'phone': str(profile.get('phone') or '').strip()[:40],
        'first_name': first_name,
        'last_name': last_name,
    }, None


def _customer(member):
    item, conflict = resolve_app_booking_identity(
        email=member['email'], phone=member['phone'],
        first_name=member['first_name'], last_name=member['last_name'])
    if conflict:
        raise ValueError(conflict)
    if item:
        # Booking is not a medical identity-change operation. Never overwrite
        # existing patient name/phone on a booking submission.
        return item
    return Customer.objects.create(
        first_name=member['first_name'], last_name=member['last_name'],
        phone=member['phone'], email=member['email'],
    )


def _app_booking_customer(member):
    """Read the same scoped patient without modifying records."""
    customer, conflict = resolve_app_booking_identity(
        email=member['email'], phone=member['phone'],
        first_name=member['first_name'], last_name=member['last_name'],
    )
    return customer if not conflict else None


def _eligible_staff(service, staff_id=None):
    items = StaffMember.objects.filter(active=True, services=service).distinct().order_by('sort_order', 'display_name')
    if staff_id:
        items = items.filter(pk=staff_id)
    return items


def _pick_staff(service, starts_at, staff_id=None, exclude_appointment_id=None):
    local_day = starts_at.astimezone(timezone.get_current_timezone()).date()
    for candidate in _eligible_staff(service, staff_id):
        if starts_at in available_slots(
            service,
            candidate,
            local_day,
            exclude_appointment_id=exclude_appointment_id,
        ):
            return candidate
    return None


def _appointment_payload(item):
    return {
        'id': str(item.public_id),
        'service_id': item.service_id,
        'service_slug': item.service.slug,
        'service': item.service.name,
        'staff_id': item.staff_id,
        'staff': item.staff.display_name,
        'starts_at': item.starts_at.isoformat(),
        'status': item.get_status_display(),
        'status_code': item.status,
    }


@csrf_exempt
@require_http_methods(['GET'])
def mobile_slots(request):
    service = Service.objects.filter(
        pk=request.GET.get('service_id'), active=True, bookable=True,
    ).first()
    if not service:
        return _error('service_not_found', 'Diese Terminart ist aktuell nicht verfügbar.', 400)

    day = parse_date(str(request.GET.get('day') or ''))
    if not day:
        return _error('invalid_day', 'Bitte wählen Sie ein gültiges Datum.', 400)
    if day < timezone.localdate() or day > timezone.localdate() + timedelta(days=BOOKING_HORIZON_DAYS):
        return _error('invalid_day', 'Dieses Datum liegt außerhalb des Buchungszeitraums.', 400)

    staff_id = request.GET.get('staff_id') or None
    exclude_id = request.GET.get('exclude_appointment_id') or None
    staff = _eligible_staff(service, staff_id)
    if not staff.exists():
        return _error('staff_not_found', 'Für diese Terminart ist aktuell kein passender Termin verfügbar.', 400)

    slots = set()
    for member in staff:
        slots.update(available_slots(service, member, day, exclude_appointment_id=exclude_id))
    return JsonResponse({
        'ok': True,
        'service_id': service.pk,
        'day': day.isoformat(),
        'slots': [item.isoformat() for item in sorted(slots)],
    })



def _same_booking_for_member(item, member, service, starts_at, requested_staff_id):
    """Replay only this member's exact appointment; an idempotency key is not proof of ownership."""
    return (
        item.customer.email.casefold() == member['email'].casefold()
        and item.service_id == service.pk
        and item.starts_at == starts_at
        and (not requested_staff_id or str(item.staff_id) == str(requested_staff_id))
    )


def _booking_result(item, *, created, authorization):
    """The canonical record is saved even if a secondary package bridge is unavailable."""
    try:
        package = sync_package(authorization, 'reserve', item)
    except Exception:
        logger.exception('Package bridge failed after appointment persistence')
        package = {'ok': False, 'package_used': False, 'error': 'package_service_unavailable'}
    return JsonResponse({
        'ok': True,
        'appointment_id': str(item.public_id),
        'status': item.get_status_display(),
        'status_code': item.status,
        'staff': item.staff.display_name,
        'starts_at': item.starts_at.isoformat(),
        'package': package,
    }, status=201 if created else 200)


def _safe_new_booking_notifications(item):
    """Never turn a saved appointment into HTTP 500 because a notification fails."""
    for sender in (send_booking_emails, notify_booking_created):
        try:
            sender(item)
        except Exception:
            logger.exception('Post-booking notification failed for appointment id=%s', item.pk)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def mobile_booking(request):
    member, error = _member(request)
    if error:
        return error
    authorization = request.headers.get('Authorization', '').strip()

    if request.method == 'POST':
        if is_blocked_demo_customer(member['email']):
            log_blocked_demo_booking("mobile_app")
            return blocked_demo_response()
        data = _json(request)
        service = Service.objects.filter(pk=data.get('service_id'), active=True, bookable=True).first()
        if not service:
            return _error('service_not_found', 'Diese Terminart ist aktuell nicht verfügbar.', 400)

        starts_at = parse_datetime(str(data.get('starts_at') or ''))
        if not starts_at:
            return _error('invalid_start_time', 'Bitte wählen Sie Datum und Uhrzeit.', 400)
        if timezone.is_naive(starts_at):
            starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
        supplied_key = (request.headers.get('Idempotency-Key') or '').strip()[:80]
        if supplied_key:
            idem_key = supplied_key
        else:
            digest = hashlib.sha256(
                f"app|{member['email']}|{service.pk}|{starts_at.isoformat()}".encode('utf-8')
            ).hexdigest()[:60]
            idem_key = f'app-{digest}'

        # Check idempotency BEFORE rechecking the occupied slot. Otherwise a
        # successful booking whose HTTP response was lost becomes a false 409
        # on every retry, even though the patient's appointment already exists.
        previous = Appointment.objects.select_related('customer', 'service', 'staff').filter(
            idempotency_key=idem_key,
        ).first()
        if previous:
            if not _same_booking_for_member(previous, member, service, starts_at, data.get('staff_id')):
                return _error('time_not_available', 'Diese Zeit ist inzwischen nicht mehr verfügbar.', 409)
            if previous.status in ('new', 'confirmed'):
                return _booking_result(previous, created=False, authorization=authorization)
            if supplied_key:
                return _error('booking_attempt_closed',
                              'Dieser Buchungsversuch wurde bereits abgeschlossen. Bitte wählen Sie den Termin erneut.', 409)
            # Legacy callers without a key can rebook a previously cancelled
            # appointment; their replacement receives a distinct key.
            idem_key = f'{idem_key[:62]}-{int(timezone.now().timestamp())}'[:80]

        if starts_at < timezone.now() + LEAD_TIME:
            return _error('start_time_too_soon', 'Bitte wählen Sie einen späteren Termin.', 400)

        staff = _pick_staff(service, starts_at, data.get('staff_id'))
        if not staff:
            return _error('time_not_available', 'Diese Zeit ist inzwischen nicht mehr verfügbar.', 409)

        try:
            customer = _customer(member)
        except ValueError as exc:
            if str(exc) == 'missing_name':
                return _error('profile_completion_required',
                              'Bitte ergänze deinen Vor- und Nachnamen in deinem Profil.', 422)
            return _error('identity_conflict',
                          'Die Patientendaten können nicht eindeutig zugeordnet werden. Bitte kontaktiere die Praxis.', 409)
        legacy_consent = bool(data.get('consent_acknowledged'))
        marketing_opt_in = bool(data.get('marketing_opt_in', True))
        cancellation_terms_accepted = bool(data.get('cancellation_terms_accepted', legacy_consent))
        privacy_accepted = bool(data.get('privacy_accepted', legacy_consent))

        try:
            appointment, created = create_appointment(
                customer=customer,
                service=service,
                staff=staff,
                starts_at=starts_at,
                message=str(data.get('notes') or ''),
                idempotency_key=idem_key,
                source='app',
                marketing_opt_in=marketing_opt_in,
                cancellation_terms_accepted=cancellation_terms_accepted,
                privacy_accepted=privacy_accepted,
            )
        except (ValueError, ValidationError, IntegrityError):
            # Includes model overlap validation and concurrent unique-key races.
            existing = Appointment.objects.select_related('customer', 'service', 'staff').filter(
                idempotency_key=idem_key,
            ).first()
            if existing and existing.status in ('new', 'confirmed') and _same_booking_for_member(
                existing, member, service, starts_at, data.get('staff_id')
            ):
                return _booking_result(existing, created=False, authorization=authorization)
            return _error('time_not_available', 'Diese Zeit ist inzwischen nicht mehr verfügbar.', 409)

        if created:
            transaction.on_commit(lambda appointment=appointment: _safe_new_booking_notifications(appointment))
        return _booking_result(appointment, created=created, authorization=authorization)

    services = Service.objects.filter(active=True, bookable=True).order_by('sort_order', 'name')
    staff = StaffMember.objects.filter(active=True).prefetch_related('services').order_by('sort_order', 'display_name')
    customer = _app_booking_customer(member)
    appointments = Appointment.objects.none()
    if customer:
        appointments = Appointment.objects.filter(customer=customer).select_related('service', 'staff').order_by('-starts_at')[:20]
    next_appointment = None
    if customer:
        next_appointment = Appointment.objects.filter(
            customer=customer,
            status__in=['new', 'confirmed'],
            starts_at__gte=timezone.now(),
        ).select_related('service', 'staff').order_by('starts_at').first()

    return JsonResponse({
        'ok': True,
        'slot_mode': True,
        'services': [
            {
                'id': item.pk,
                'slug': item.slug,
                'name': item.name,
                'duration_minutes': item.duration_minutes,
                'price_label': item.price_label,
            }
            for item in services
        ],
        'staff': [
            {
                'id': item.pk,
                'name': item.display_name,
                'service_ids': list(item.services.filter(active=True, bookable=True).values_list('id', flat=True)),
            }
            for item in staff
        ],
        'appointments': [_appointment_payload(item) for item in appointments],
        'next_appointment': _appointment_payload(next_appointment) if next_appointment else None,
    })


@csrf_exempt
@require_http_methods(['GET'])
def mobile_manageable_appointments(request):
    member, error = _member(request)
    if error:
        return error
    customer = _app_booking_customer(member)
    items = Appointment.objects.none()
    if customer:
        items = Appointment.objects.filter(
            customer=customer,
            status__in=['new', 'confirmed'],
            starts_at__gt=timezone.now(),
        ).select_related('service', 'staff').order_by('starts_at')[:20]
    staff = StaffMember.objects.filter(active=True).prefetch_related('services').order_by('sort_order', 'display_name')
    now = timezone.now()
    return JsonResponse({
        'ok': True,
        'change_deadline_hours': CHANGE_DEADLINE_HOURS,
        'appointments': [
            {
                **_appointment_payload(item),
                'change_allowed': now <= item.starts_at - timedelta(hours=CHANGE_DEADLINE_HOURS),
            }
            for item in items
        ],
        'staff': [
            {
                'id': item.pk,
                'name': item.display_name,
                'service_ids': list(item.services.filter(active=True, bookable=True).values_list('id', flat=True)),
            }
            for item in staff
        ],
    })


@csrf_exempt
@require_http_methods(['POST'])
def mobile_appointment_change(request, appointment_id):
    member, error = _member(request)
    if error:
        return error
    authorization = request.headers.get('Authorization', '').strip()
    data = _json(request)
    action = str(data.get('action') or '').strip().lower()
    if action not in {'cancel', 'reschedule'}:
        return _error('invalid_change_action', 'Diese Änderung ist nicht möglich.', 400)

    customer = _app_booking_customer(member)
    if not customer:
        return _error('appointment_not_found', 'Termin nicht gefunden.', 404)

    with transaction.atomic():
        item = Appointment.objects.select_for_update().select_related('service', 'staff').filter(
            public_id=appointment_id,
            customer=customer,
        ).first()
        if not item:
            return _error('appointment_not_found', 'Termin nicht gefunden.', 404)
        if item.status not in {'new', 'confirmed'}:
            return _error('appointment_not_changeable', 'Dieser Termin kann nicht mehr geändert werden.', 409)
        if timezone.now() > item.starts_at - timedelta(hours=CHANGE_DEADLINE_HOURS):
            return JsonResponse({
                'ok': False,
                'error': 'change_deadline_passed',
                'message': 'Die Änderungsfrist für diesen Termin ist abgelaufen.',
                'deadline_hours': CHANGE_DEADLINE_HOURS,
            }, status=409)

        if action == 'cancel':
            item.status = 'cancelled'
            item.save(update_fields=['status', 'updated_at'])
        else:
            starts_at = parse_datetime(str(data.get('starts_at') or ''))
            if not starts_at:
                return _error('invalid_start_time', 'Bitte wählen Sie Datum und Uhrzeit.', 400)
            if timezone.is_naive(starts_at):
                starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
            if starts_at < timezone.now() + LEAD_TIME:
                return _error('start_time_too_soon', 'Bitte wählen Sie einen späteren Termin.', 400)

            staff = _pick_staff(
                item.service,
                starts_at,
                data.get('staff_id'),
                exclude_appointment_id=str(item.public_id),
            )
            if not staff:
                return _error('time_not_available', 'Diese Zeit ist inzwischen nicht mehr verfügbar.', 409)

            duration = timedelta(minutes=item.service.duration_minutes + item.service.buffer_minutes)
            item.staff = staff
            item.starts_at = starts_at
            item.ends_at = starts_at + duration
            item.status = 'new' if item.service.requires_confirmation else 'confirmed'
            item.reminder_1h_sent_at = None
            item.reminder_1h_admin_email_sent_at = None
            item.reminder_1h_admin_push_sent_at = None
            item.full_clean()
            item.save(update_fields=[
                'staff', 'starts_at', 'ends_at', 'status', 'reminder_1h_sent_at',
                'reminder_1h_admin_email_sent_at', 'reminder_1h_admin_push_sent_at',
                'updated_at',
            ])

    if action == 'cancel':
        notify_customer_cancelled(item)
        package = sync_package(authorization, 'release', item)
        return JsonResponse({
            'ok': True,
            'action': 'cancel',
            'status': item.get_status_display(),
            'package': package,
        })

    notify_customer_rescheduled(item)
    return JsonResponse({
        'ok': True,
        'action': 'reschedule',
        'appointment': _appointment_payload(item),
    })
