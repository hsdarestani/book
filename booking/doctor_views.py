"""An independent clinician workspace. Every query and write is bound to the SSO-linked staff id."""
import calendar
from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Appointment, BlockedPeriod, DailyAvailabilityOverride, WorkingHour
from .customer_identity import resolve_patient_identity
from .notifications import appointment_snapshot, notify_admin_changed
from .services import available_slots, effective_working_ranges
from .views import _calendar_position, _calendar_block_kind, _clean_calendar_reason, CALENDAR_START_HOUR, CALENDAR_END_HOUR


MONTH_NAMES = ('', 'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
               'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember')
WEEKDAY_NAMES = ('Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag')


def _doctor_staff(request):
    """The SSO profile is the source of truth, never a client supplied staff id."""
    profile = getattr(request.user, 'aesthetic_access', None)
    if not profile or not profile.view_only or not profile.staff_id:
        return None
    staff = profile.staff
    if not staff or staff.display_name.strip().casefold() != 'qamar hameed' or staff.role != 'doctor':
        return None
    return staff


def _redirect(day, notice):
    return redirect('/verwaltung/arzt/?date=' + day.isoformat() + '&notice=' + notice)


def _time(value):
    result = parse_time(str(value or ''))
    return result if result and result.second == 0 and result.minute % 15 == 0 else None


def _working_ranges(post):
    first = (_time(post.get('start_1')), _time(post.get('end_1')))
    second_raw = (post.get('start_2'), post.get('end_2'))
    second = (_time(second_raw[0]), _time(second_raw[1])) if any(second_raw) else (None, None)
    if not first[0] or not first[1] or first[1] <= first[0]:
        raise ValidationError('Bitte gültige Zeiten im 15 Minuten Raster eingeben.')
    if any(second_raw):
        if not second[0] or not second[1] or second[1] <= second[0] or second[0] < first[1]:
            raise ValidationError('Der zweite Zeitraum ist ungültig.')
        return [first, second]
    return [first]


def _save_availability(staff, day, post):
    action = post.get('action')
    if action == 'reset':
        DailyAvailabilityOverride.objects.filter(staff_id=staff.pk, date=day).delete()
        return
    closed = post.get('closed') == 'on'
    ranges = [] if closed else _working_ranges(post)
    override = DailyAvailabilityOverride.objects.filter(staff_id=staff.pk, date=day).first()
    if override is None:
        override = DailyAvailabilityOverride(staff=staff, date=day)
    override.closed = closed
    override.start_time_1 = ranges[0][0] if ranges else None
    override.end_time_1 = ranges[0][1] if ranges else None
    override.start_time_2 = ranges[1][0] if len(ranges) > 1 else None
    override.end_time_2 = ranges[1][1] if len(ranges) > 1 else None
    override.full_clean()
    override.save()


def _save_weekly(staff, weekday, post):
    if weekday not in range(7):
        raise ValidationError('Ungültiger Wochentag.')
    ranges = [] if post.get('closed') == 'on' else _working_ranges(post)
    # Validations must complete before replacing the clinician's existing rows.
    new = [WorkingHour(staff=staff, weekday=weekday, start_time=start, end_time=end)
           for start, end in ranges]
    for item in new:
        item.clean()
    WorkingHour.objects.filter(staff_id=staff.pk, weekday=weekday).delete()
    for item in new:
        item.save()


def _change_appointment(staff, post):
    appointment_id = str(post.get('appointment_id') or '')
    if not appointment_id.isdigit():
        raise ValidationError('Termin nicht gefunden.')
    appointment = (Appointment.objects.select_for_update()
                   .select_related('customer', 'service', 'staff')
                   .filter(pk=int(appointment_id), staff_id=staff.pk).first())
    if not appointment:
        raise ValidationError('Termin nicht gefunden.')
    previous = appointment_snapshot(appointment)
    if post.get('action') == 'status':
        status = str(post.get('status') or '')
        if status not in {value for value, _ in Appointment.STATUS}:
            raise ValidationError('Ungültiger Status.')
        appointment.status = status
    else:
        if appointment.status == 'cancelled':
            raise ValidationError('Abgesagte Termine können nicht verschoben werden.')
        new_day = parse_date(str(post.get('new_date') or ''))
        new_time = _time(post.get('new_time'))
        if not new_day or not new_time:
            raise ValidationError('Ungültige Uhrzeit oder Datum.')
        starts = timezone.make_aware(datetime.combine(new_day, new_time), timezone.get_current_timezone())
        if starts not in available_slots(appointment.service, staff, new_day,
                                        exclude_appointment_id=appointment.public_id):
            raise ValidationError('Diese Uhrzeit ist nicht verfügbar.')
        appointment.starts_at = starts
        appointment.ends_at = starts + timedelta(
            minutes=appointment.service.duration_minutes + appointment.service.buffer_minutes)
        appointment.reminder_1h_sent_at = None
        appointment.reminder_24h_sent_at = None
    appointment.full_clean()
    appointment.save()
    return appointment, previous


def _save_full_week(staff, post):
    proposed = []
    for weekday in range(7):
        if post.get(f'day_{weekday}_enabled') != 'on':
            continue
        first = {'start_1': post.get(f'day_{weekday}_start_1'),
                 'end_1': post.get(f'day_{weekday}_end_1'),
                 'start_2': post.get(f'day_{weekday}_start_2'),
                 'end_2': post.get(f'day_{weekday}_end_2')}
        for start, end in _working_ranges(first):
            item = WorkingHour(staff=staff, weekday=weekday, start_time=start, end_time=end)
            item.clean()
            proposed.append(item)
    WorkingHour.objects.filter(staff_id=staff.pk).delete()
    for item in proposed:
        item.save()


def _calendar_block(staff, post):
    action = post.get('action')
    if action in {'delete_calendar_item', 'delete_block'}:
        ident = str(post.get('block_id') or '')
        if not ident.isdigit():
            raise ValidationError('Sperrzeit nicht gefunden.')
        changed = BlockedPeriod.objects.filter(pk=int(ident), staff_id=staff.pk).delete()
        if not changed[0]:
            raise ValidationError('Sperrzeit nicht gefunden.')
        return
    block_date = parse_date(str(post.get('block_date') or post.get('note_date') or post.get('date') or ''))
    start = _time(post.get('block_start') or post.get('note_start'))
    end = _time(post.get('block_end') or post.get('note_end'))
    if not block_date or not start or not end or end <= start:
        raise ValidationError('Bitte gültige Sperrzeit angeben.')
    if block_date < timezone.localdate() - timedelta(days=730) or block_date > timezone.localdate() + timedelta(days=730):
        raise ValidationError('Datum außerhalb des erlaubten Bereichs.')
    starts_at = timezone.make_aware(datetime.combine(block_date, start), timezone.get_current_timezone())
    ends_at = timezone.make_aware(datetime.combine(block_date, end), timezone.get_current_timezone())
    is_note = action == 'add_calendar_note'
    label = (post.get('note_text') if is_note else (post.get('block_text') or post.get('block_reason'))) or ('Notiz' if is_note else 'Gesperrt')
    prefix = '[NOTE][STAFF] ' if is_note and post.get('note_blocked') != 'on' else '[BLOCKNOTE][STAFF] '
    reason = prefix + str(label).strip()[:120]
    BlockedPeriod.objects.create(staff=staff, starts_at=starts_at, ends_at=ends_at, reason=reason[:160])



def _own_customer_ids(staff):
    from .models import DoctorPatientAccess
    return set(Appointment.objects.filter(staff_id=staff.pk).values_list('customer_id', flat=True)) | set(
        DoctorPatientAccess.objects.filter(staff_id=staff.pk).values_list('customer_id', flat=True)
    )


def _edit_own_block(staff, post):
    ident = str(post.get('block_id') or '')
    if not ident.isdigit():
        raise ValidationError('Eintrag nicht gefunden.')
    item = BlockedPeriod.objects.select_for_update().filter(pk=int(ident), staff_id=staff.pk).first()
    if not item:
        raise ValidationError('Eintrag nicht gefunden.')
    day = parse_date(str(post.get('item_date') or ''))
    start, end = _time(post.get('item_start')), _time(post.get('item_end'))
    if not day or not start or not end or end <= start:
        raise ValidationError('Ungültiger Zeitraum.')
    kind = str(post.get('item_kind') or '')
    if kind not in {'note', 'block'}:
        raise ValidationError('Ungültiger Eintrag.')
    prefix = '[NOTE][STAFF] ' if kind == 'note' else '[BLOCKNOTE][STAFF] '
    item.starts_at = timezone.make_aware(datetime.combine(day, start), timezone.get_current_timezone())
    item.ends_at = timezone.make_aware(datetime.combine(day, end), timezone.get_current_timezone())
    item.reason = (prefix + str(post.get('item_text') or '').strip())[:160]
    item.full_clean()
    item.save()


def _edit_own_appointment(staff, post):
    from .models import Customer, Service
    ident = str(post.get('appointment_id') or '')
    if not ident.isdigit():
        raise ValidationError('Termin nicht gefunden.')
    item = (Appointment.objects.select_for_update()
            .select_related('customer', 'service', 'staff')
            .filter(pk=int(ident), staff_id=staff.pk).first())
    if not item:
        raise ValidationError('Termin nicht gefunden.')
    if str(post.get('appointment_staff_id') or staff.pk) != str(staff.pk):
        raise ValidationError('Andere Ärzte sind nicht zugelassen.')
    patient_id = str(post.get('customer_id') or '')
    if not patient_id.isdigit() or not Customer.objects.filter(
            pk=int(patient_id), pk__in=_own_customer_ids(staff)).exists():
        raise ValidationError('Patient nicht zugeordnet.')
    service = Service.objects.filter(
        pk=post.get('service_id'), staff_members=staff, active=True).first()
    day = parse_date(str(post.get('appointment_date') or ''))
    time_value = _time(post.get('appointment_time'))
    new_status = str(post.get('status') or '')
    if not service or not day or not time_value or new_status not in {k for k, _ in Appointment.STATUS}:
        raise ValidationError('Ungültiger Termin.')
    new_start = timezone.make_aware(datetime.combine(day, time_value), timezone.get_current_timezone())
    # Prevent collisions and booking during closure; retaining an unchanged
    # appointment during a subsequently closed day remains valid.
    changing_time = new_start != item.starts_at or service.pk != item.service_id
    if changing_time and new_status in {'new', 'confirmed'}:
        if new_start not in available_slots(service, staff, day, exclude_appointment_id=item.public_id):
            raise ValidationError('Zeitfenster nicht verfügbar.')
    previous = appointment_snapshot(item)
    item.service = service
    item.starts_at = new_start
    item.ends_at = new_start + timedelta(minutes=service.duration_minutes + service.buffer_minutes)
    item.status = new_status
    if new_start.isoformat() != previous['starts_at']:
        item.reminder_1h_sent_at = None
        item.reminder_24h_sent_at = None
    item.full_clean()
    item.save()
    return item, previous


def _delete_own_appointment(staff, post):
    from .notifications import notify_admin_deleted
    ident = str(post.get('appointment_id') or '')
    if not ident.isdigit():
        raise ValidationError('Termin nicht gefunden.')
    item = (Appointment.objects.select_related('customer', 'service', 'staff')
            .filter(pk=int(ident), staff_id=staff.pk).first())
    if not item:
        raise ValidationError('Termin nicht gefunden.')
    transaction.on_commit(lambda appointment=item: notify_admin_deleted(appointment))
    item.delete()


def _create_own_appointment(staff, post):
    from .models import Customer, Service
    from .notifications import notify_admin_created
    from .services import create_appointment
    service = Service.objects.filter(pk=post.get('service_id'), staff_members=staff, active=True).first()
    patient_id = str(post.get('customer_id') or '')
    patient = Customer.objects.filter(
        pk=int(patient_id), pk__in=_own_customer_ids(staff)).first() if patient_id.isdigit() else None
    day = parse_date(str(post.get('appointment_date') or ''))
    time_value = _time(post.get('appointment_time'))
    if not service or not patient or not day or not time_value:
        raise ValidationError('Ungültige Buchung.')
    starts = timezone.make_aware(datetime.combine(day, time_value), timezone.get_current_timezone())
    try:
        item, created = create_appointment(
            customer=patient, service=service, staff=staff, starts_at=starts, source='admin')
    except ValueError:
        raise ValidationError('Zeitfenster nicht verfügbar.')
    if created:
        transaction.on_commit(lambda item=item: notify_admin_created(item))


def _create_own_customer(staff, post):
    from .models import Customer
    first = str(post.get('first_name') or '').strip()[:80]
    last = str(post.get('last_name') or '').strip()[:80]
    email = str(post.get('email') or '').strip().lower()[:254]
    if not first or '@' not in email:
        raise ValidationError('Name und E-Mail erforderlich.')
    existing, conflict = resolve_patient_identity(
        email=email, phone=post.get('phone'), first_name=first, last_name=last)
    if conflict:
        raise ValidationError('Patientendaten sind widersprüchlich. Bitte Verwaltung prüfen.')
    if existing and existing.pk not in _own_customer_ids(staff):
        raise ValidationError('Patient kann hier nicht übernommen werden.')
    from .models import DoctorPatientAccess
    if existing:
        # A shared patient may have visits with other providers. Clinic-wide
        # identity fields cannot be edited using a clinician-only account.
        if Appointment.objects.filter(customer=existing).exclude(staff_id=staff.pk).exists():
            raise ValidationError('Gemeinsame Patienten können nur durch die Verwaltung geändert werden.')
        existing.first_name = first
        existing.last_name = last or existing.last_name
        existing.save(update_fields=['first_name', 'last_name', 'updated_at'])
        DoctorPatientAccess.objects.get_or_create(staff=staff, customer=existing)
    else:
        created = Customer.objects.create(first_name=first, last_name=last, email=email,
                                          phone=str(post.get('phone') or '')[:40])
        DoctorPatientAccess.objects.create(staff=staff, customer=created)


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def doctor_appointments(request):
    """The same shared admin calendar, with doctor-only queries and writes."""
    staff = _doctor_staff(request)
    if not staff:
        return HttpResponseForbidden('Kein Arztzugang.')

    today = timezone.localdate()
    params = request.POST if request.method == 'POST' else request.GET
    day = parse_date(str(params.get('date') or params.get('return_date') or request.GET.get('date') or '')) or today
    if day < today - timedelta(days=730) or day > today + timedelta(days=730):
        return HttpResponseForbidden('Datum außerhalb des zulässigen Bereichs.')
    cal_view = str(params.get('cal_view') or params.get('return_view') or 'day')
    if cal_view not in {'day', 'week', 'provider', 'service'}:
        cal_view = 'day'
    section = str(request.GET.get('section') or request.POST.get('section') or 'calendar')
    if section not in {'dashboard', 'calendar', 'bookings', 'customers', 'settings', 'information'}:
        section = 'calendar'

    if request.method == 'POST':
        action = str(request.POST.get('action') or '')
        changed = None
        try:
            with transaction.atomic():
                if action in {'save', 'reset'}:
                    _save_availability(staff, day, request.POST)
                elif action == 'weekly':
                    _save_weekly(staff, day.weekday(), request.POST)
                elif action == 'save_hours':
                    _save_full_week(staff, request.POST)
                elif action in {'status', 'move', 'appointment_status'}:
                    # Mirror the original admin status control without giving
                    # the clinician access to unscoped admin POST handlers.
                    if action == 'appointment_status':
                        data = request.POST.copy()
                        data['action'] = 'status'
                        changed = _change_appointment(staff, data)
                    else:
                        changed = _change_appointment(staff, request.POST)
                elif action in {'add_block', 'add_calendar_block', 'add_calendar_note', 'delete_calendar_item', 'delete_block'}:
                    _calendar_block(staff, request.POST)
                elif action == 'edit_calendar_item':
                    _edit_own_block(staff, request.POST)
                elif action == 'edit_appointment':
                    changed = _edit_own_appointment(staff, request.POST)
                elif action == 'delete_appointment':
                    _delete_own_appointment(staff, request.POST)
                elif action == 'add_appointment':
                    _create_own_appointment(staff, request.POST)
                elif action == 'add_customer':
                    _create_own_customer(staff, request.POST)
                else:
                    raise ValidationError('Aktion nicht erlaubt.')
        except (ValidationError, ValueError, TypeError):
            return redirect('/verwaltung/arzt/?section=' + section + '&date=' + day.isoformat() + '&cal_view=' + cal_view + '&notice=error')
        if changed:
            transaction.on_commit(lambda item=changed[0], old=changed[1]: notify_admin_changed(item, old))
        return redirect('/verwaltung/arzt/?section=' + section + '&date=' + day.isoformat() + '&cal_view=' + cal_view + '&notice=saved')

    # Identical template, menu and JS as the real administrator. Only the data
    # scope differs; the regular admin GET handler never executes a doctor POST.
    from . import admin_views, views
    request.doctor_staff_scope = staff
    response = views.dashboard(request)
    return admin_views._polish_admin_response(
        response, selected_staff_id=staff.pk, calendar_day=day,
        calendar_view=cal_view, doctor_staff_id=staff.pk,
        focus_block=request.GET.get('focus_block'),
        focus_appointment=request.GET.get('focus_appointment'),
        notice=request.GET.get('notice') or '',
    )
