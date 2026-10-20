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
            item.full_clean(validate_unique=False)
            proposed.append(item)
    WorkingHour.objects.filter(staff_id=staff.pk).delete()
    for item in proposed:
        item.save()


def _calendar_block(staff, post):
    action = post.get('action')
    if action == 'delete_calendar_item':
        ident = str(post.get('block_id') or '')
        if not ident.isdigit():
            raise ValidationError('Sperrzeit nicht gefunden.')
        changed = BlockedPeriod.objects.filter(pk=int(ident), staff_id=staff.pk).delete()
        if not changed[0]:
            raise ValidationError('Sperrzeit nicht gefunden.')
        return
    block_date = parse_date(str(post.get('block_date') or post.get('date') or ''))
    start = _time(post.get('block_start'))
    end = _time(post.get('block_end'))
    if not block_date or not start or not end or end <= start:
        raise ValidationError('Bitte gültige Sperrzeit angeben.')
    if block_date < timezone.localdate() - timedelta(days=730) or block_date > timezone.localdate() + timedelta(days=730):
        raise ValidationError('Datum außerhalb des erlaubten Bereichs.')
    starts_at = timezone.make_aware(datetime.combine(block_date, start), timezone.get_current_timezone())
    ends_at = timezone.make_aware(datetime.combine(block_date, end), timezone.get_current_timezone())
    is_note = action == 'add_calendar_note'
    label = (post.get('note_text') if is_note else post.get('block_text')) or ('Notiz' if is_note else 'Gesperrt')
    reason = ('[NOTE][STAFF] ' if is_note else '[BLOCKNOTE][STAFF] ') + str(label).strip()[:120]
    BlockedPeriod.objects.create(staff=staff, starts_at=starts_at, ends_at=ends_at, reason=reason[:160])


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
    day = parse_date(str(params.get('date') or params.get('return_date') or '')) or today
    if day < today - timedelta(days=730) or day > today + timedelta(days=730):
        return HttpResponseForbidden('Datum außerhalb des zulässigen Bereichs.')
    cal_view = str(params.get('cal_view') or params.get('return_view') or 'day')
    if cal_view not in {'day', 'week'}:
        cal_view = 'day'

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
                        from django.http import QueryDict
                        data = request.POST.copy()
                        data['action'] = 'status'
                        changed = _change_appointment(staff, data)
                    else:
                        changed = _change_appointment(staff, request.POST)
                elif action in {'add_block', 'add_calendar_block', 'add_calendar_note', 'delete_calendar_item'}:
                    _calendar_block(staff, request.POST)
                else:
                    raise ValidationError('Aktion nicht erlaubt.')
        except (ValidationError, ValueError, TypeError):
            return redirect('/verwaltung/arzt/?date=' + day.isoformat() + '&cal_view=' + cal_view + '&notice=error')
        if changed:
            transaction.on_commit(lambda item=changed[0], old=changed[1]: notify_admin_changed(item, old))
        return redirect('/verwaltung/arzt/?date=' + day.isoformat() + '&cal_view=' + cal_view + '&notice=saved')

    now = timezone.now()
    if cal_view == 'week':
        range_start = day - timedelta(days=day.weekday())
        range_end = range_start + timedelta(days=7)
        previous_date, next_date = range_start - timedelta(days=7), range_start + timedelta(days=7)
    else:
        range_start = day
        range_end = day + timedelta(days=1)
        previous_date, next_date = day - timedelta(days=1), day + timedelta(days=1)
    start_dt = timezone.make_aware(datetime.combine(range_start, datetime.min.time()), timezone.get_current_timezone())
    end_dt = timezone.make_aware(datetime.combine(range_end, datetime.min.time()), timezone.get_current_timezone())
    shown = list(
        Appointment.objects.filter(staff_id=staff.pk, starts_at__lt=end_dt, ends_at__gt=start_dt)
        .exclude(status='cancelled').select_related('customer', 'service', 'staff').order_by('starts_at'))
    blocks = list(
        BlockedPeriod.objects.filter(staff_id=staff.pk, starts_at__lt=end_dt, ends_at__gt=start_dt)
        .order_by('starts_at'))
    calendar_days = []
    cursor = range_start
    while cursor < range_end:
        ranges, _ = effective_working_ranges(staff, cursor)
        segments = []
        for start, end in ranges:
            starts_at = timezone.make_aware(datetime.combine(cursor, start), timezone.get_current_timezone())
            ends_at = timezone.make_aware(datetime.combine(cursor, end), timezone.get_current_timezone())
            top, height = _calendar_position(starts_at, ends_at)
            segments.append({'top': top, 'height': height, 'label': f'{start:%H:%M}–{end:%H:%M}'})
        day_appointments = []
        for item in shown:
            if timezone.localtime(item.starts_at).date() != cursor:
                continue
            top, height = _calendar_position(item.starts_at, item.ends_at)
            day_appointments.append({'item': item, 'top': top, 'height': height})
        day_blocks = []
        for item in blocks:
            if timezone.localtime(item.starts_at).date() != cursor:
                continue
            top, height = _calendar_position(item.starts_at, item.ends_at)
            day_blocks.append({'item': item, 'top': top, 'height': height,
                               'kind': _calendar_block_kind(item.reason),
                               'label': _clean_calendar_reason(item.reason)})
        calendar_days.append({
            'date': cursor, 'day_name': ('Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So')[cursor.weekday()],
            'working_segments': segments, 'appointments': day_appointments,
            'blocks': day_blocks, 'is_today': cursor == today,
        })
        cursor += timedelta(days=1)

    hours = {weekday: [] for weekday in range(7)}
    for item in WorkingHour.objects.filter(staff_id=staff.pk, active=True).order_by('weekday', 'start_time'):
        hours[item.weekday].append(item)
    availability_rows = []
    for weekday in range(7):
        intervals = hours[weekday][:2]
        availability_rows.append({
            'weekday': weekday, 'label': WEEKDAY_NAMES[weekday], 'enabled': bool(intervals),
            'start_1': intervals[0].start_time.strftime('%H:%M') if intervals else '09:00',
            'end_1': intervals[0].end_time.strftime('%H:%M') if intervals else '18:00',
            'start_2': intervals[1].start_time.strftime('%H:%M') if len(intervals) > 1 else '',
            'end_2': intervals[1].end_time.strftime('%H:%M') if len(intervals) > 1 else '',
        })
    upcoming = list(
        Appointment.objects.filter(staff_id=staff.pk, starts_at__gte=now)
        .select_related('customer', 'service', 'staff').order_by('starts_at')[:80])
    own_customers = len({item.customer_id for item in Appointment.objects.filter(staff_id=staff.pk).only('customer_id')})
    daily_ranges, override = effective_working_ranges(staff, day)
    return render(request, 'booking/doctor_appointments.html', {
        'doctor_mode': True, 'staff': staff, 'selected_staff': staff, 'staff_members': [staff],
        'today': today, 'day': day, 'calendar_date': day, 'calendar_view': cal_view,
        'range_start': range_start, 'range_end_display': range_end - timedelta(days=1),
        'previous_date': previous_date, 'next_date': next_date, 'calendar_days': calendar_days,
        'calendar_hour_labels': [f'{hour:02d}:00' for hour in range(CALENDAR_START_HOUR, CALENDAR_END_HOUR + 1)],
        'today_count': Appointment.objects.filter(staff_id=staff.pk, starts_at__date=today).exclude(status='cancelled').count(),
        'new_count': Appointment.objects.filter(staff_id=staff.pk, starts_at__gte=now, status='new').count(),
        'customer_count': own_customers, 'upcoming': upcoming,
        'appointment_statuses': Appointment.STATUS, 'availability_rows': availability_rows,
        'blocked_periods': BlockedPeriod.objects.filter(staff_id=staff.pk, ends_at__gte=now).order_by('starts_at')[:30],
        'ranges': daily_ranges, 'override': override,
        'notice': request.GET.get('notice') if request.GET.get('notice') in {'saved', 'error'} else '',
    })
