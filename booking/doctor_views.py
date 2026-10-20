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

from .models import Appointment, DailyAvailabilityOverride, WorkingHour
from .notifications import appointment_snapshot, notify_admin_changed
from .services import available_slots, effective_working_ranges


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


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def doctor_appointments(request):
    staff = _doctor_staff(request)
    if not staff:
        return HttpResponseForbidden('Kein Arztzugang.')

    today = timezone.localdate()
    day = parse_date((request.POST if request.method == 'POST' else request.GET).get('date') or '') or today
    if day < today - timedelta(days=730) or day > today + timedelta(days=730):
        return HttpResponseForbidden('Datum außerhalb des zulässigen Bereichs.')

    if request.method == 'POST':
        action = str(request.POST.get('action') or '')
        changed = None
        try:
            with transaction.atomic():
                if action in {'save', 'reset'}:
                    _save_availability(staff, day, request.POST)
                elif action == 'weekly':
                    _save_weekly(staff, day.weekday(), request.POST)
                elif action in {'status', 'move'}:
                    changed = _change_appointment(staff, request.POST)
                else:
                    raise ValidationError('Aktion nicht erlaubt.')
        except (ValidationError, ValueError) as exc:
            message = '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            # Messages are server-generated, but avoid turning user data into a query string.
            return _redirect(day, 'error')
        if changed:
            # Only the already scoped appointment is notified, after the DB commit.
            transaction.on_commit(lambda item=changed[0], old=changed[1]: notify_admin_changed(item, old))
        return _redirect(day, 'saved')

    month_calendar = calendar.Calendar(firstweekday=0)
    weeks = month_calendar.monthdatescalendar(day.year, day.month)
    month_start = weeks[0][0]
    month_end = weeks[-1][-1] + timedelta(days=1)
    all_appointments = (
        Appointment.objects.filter(staff_id=staff.pk, starts_at__date__gte=month_start,
                                   starts_at__date__lt=month_end)
        .exclude(status='cancelled')
        .values_list('starts_at', flat=True)
    )
    counts = {}
    for starts in all_appointments:
        local_day = timezone.localtime(starts).date()
        counts[local_day] = counts.get(local_day, 0) + 1
    overrides = {row.date: row for row in DailyAvailabilityOverride.objects.filter(
        staff_id=staff.pk, date__gte=month_start, date__lt=month_end)}
    calendar_weeks = [[{
        'date': d, 'count': counts.get(d, 0),
        'closed': bool(overrides[d].closed) if d in overrides else False,
        'other_month': d.month != day.month,
        'selected': d == day,
        'today': d == today,
    } for d in week] for week in weeks]

    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), timezone.get_current_timezone())
    end = start + timedelta(days=1)
    appointments = list(
        Appointment.objects.filter(staff_id=staff.pk, starts_at__lt=end, ends_at__gt=start)
        .select_related('customer', 'service').order_by('starts_at', 'pk'))
    ranges, override = effective_working_ranges(staff, day)
    weekly = list(WorkingHour.objects.filter(staff_id=staff.pk, weekday=day.weekday(), active=True)
                  .order_by('start_time'))
    previous_month = (day.replace(day=1) - timedelta(days=1)).replace(day=1)
    following_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    notice = request.GET.get('notice') if request.GET.get('notice') in {'saved', 'error'} else ''
    return render(request, 'booking/doctor_appointments.html', {
        'staff': staff, 'appointments': appointments, 'today': today, 'day': day,
        'calendar_weeks': calendar_weeks, 'month_name': MONTH_NAMES[day.month],
        'weekday_name': WEEKDAY_NAMES[day.weekday()],
        'previous_month': previous_month, 'following_month': following_month,
        'previous_day': day - timedelta(days=1), 'following_day': day + timedelta(days=1),
        'ranges': ranges, 'override': override, 'weekly': weekly, 'notice': notice,
    })
