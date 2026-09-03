from datetime import datetime, timedelta
import re

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from .models import Appointment, BlockedPeriod, DailyAvailabilityOverride, StaffMember
from .services import effective_working_ranges


CALENDAR_START_MINUTE = 8 * 60
CALENDAR_END_MINUTE = 20 * 60
CALENDAR_TOTAL_MINUTES = CALENDAR_END_MINUTE - CALENDAR_START_MINUTE


def _is_quarter(value):
    return bool(value) and value.minute % 15 == 0


def _fmt(value):
    return value.strftime('%H:%M') if value else ''


def _payload(staff, day):
    ranges, override = effective_working_ranges(staff, day)
    return {
        'staff_id': staff.pk,
        'date': day.isoformat(),
        'source': 'override' if override else 'weekly',
        'is_override': bool(override),
        'closed': bool(override.closed) if override else not bool(ranges),
        'ranges': [{'start': _fmt(start), 'end': _fmt(end)} for start, end in ranges],
    }


def _calendar_redirect(staff_id, day, notice='hours'):
    return redirect(f'/verwaltung/kalender/?date={day.isoformat()}&cal_view=day&staff={staff_id}&notice={notice}')


def _position(starts_at, ends_at):
    local_start = timezone.localtime(starts_at)
    local_end = timezone.localtime(ends_at)
    start_minute = max(CALENDAR_START_MINUTE, local_start.hour * 60 + local_start.minute)
    end_minute = min(CALENDAR_END_MINUTE, local_end.hour * 60 + local_end.minute)
    visible_end = max(end_minute, start_minute + 10)
    top = max(0, ((start_minute - CALENDAR_START_MINUTE) / CALENDAR_TOTAL_MINUTES) * 100)
    height = max(1.6, ((visible_end - start_minute) / CALENDAR_TOTAL_MINUTES) * 100)
    return round(top, 4), round(height, 4)


def _scope_from_reason(reason):
    value = reason or ''
    if '[ALL]' in value:
        return 'all', None
    match = re.search(r'\[SERVICE:(\d+)\]', value)
    if match:
        return 'service', match.group(1)
    return 'staff', None


def _clean_reason(reason):
    value = (reason or '').strip()
    prefixes = ('[NOTE]', '[BLOCKNOTE]', '[ALL]', '[STAFF]')
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if value.startswith(prefix):
                value = value[len(prefix):].lstrip()
                changed = True
    if value.startswith('[SERVICE:') and ']' in value:
        value = value.split(']', 1)[1].lstrip()
    return value or 'Notiz'


def _block_kind(reason):
    value = reason or ''
    return 'note' if value.startswith('[NOTE]') else 'block'


def _block_visual_kind(reason):
    value = reason or ''
    if value.startswith('[NOTE]'):
        return 'note'
    if value.startswith('[BLOCKNOTE]'):
        return 'blocked-note'
    return 'blocked'


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


def _appointment_payload(item):
    local_start = timezone.localtime(item.starts_at)
    local_end = timezone.localtime(item.ends_at)
    top, height = _position(item.starts_at, item.ends_at)
    return {
        'id': item.pk,
        'service_id': item.service_id,
        'staff_id': item.staff_id,
        'customer_id': item.customer_id,
        'date': local_start.date().isoformat(),
        'time': local_start.strftime('%H:%M'),
        'start': local_start.strftime('%H:%M'),
        'end': local_end.strftime('%H:%M'),
        'status': item.status,
        'customer_name': item.customer.full_name,
        'service_name': item.service.name,
        'staff_name': item.staff.display_name,
        'top': top,
        'height': height,
    }


def _block_payload(item):
    local_start = timezone.localtime(item.starts_at)
    local_end = timezone.localtime(item.ends_at)
    scope, service_id = _scope_from_reason(item.reason)
    top, height = _position(item.starts_at, item.ends_at)
    return {
        'id': item.pk,
        'staff_id': item.staff_id,
        'date': local_start.date().isoformat(),
        'start': local_start.strftime('%H:%M'),
        'end': local_end.strftime('%H:%M'),
        'kind': _block_kind(item.reason),
        'visual_kind': _block_visual_kind(item.reason),
        'scope': scope,
        'service_id': service_id or '',
        'text': _clean_reason(item.reason),
        'top': top,
        'height': height,
    }


def _private_json(payload, status=200):
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    return response


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET'])
def calendar_day(request):
    """Small, fast payload used by in-place day navigation in the admin calendar."""
    staff_id = request.GET.get('staff')
    day = parse_date(request.GET.get('date') or '')
    staff = StaffMember.objects.filter(pk=staff_id, active=True).first()
    if not staff or not day:
        return _private_json({'ok': False, 'error': 'invalid_request'}, status=400)

    start, end = _day_bounds(day)
    appointments = (
        Appointment.objects.filter(
            staff=staff,
            starts_at__lt=end,
            ends_at__gt=start,
        )
        .exclude(status='cancelled')
        .select_related('customer', 'service', 'staff')
        .order_by('starts_at', 'pk')
    )
    blocks = (
        BlockedPeriod.objects.filter(
            staff=staff,
            starts_at__lt=end,
            ends_at__gt=start,
        )
        .select_related('staff')
        .order_by('starts_at', 'pk')
    )

    return _private_json({
        'ok': True,
        **_payload(staff, day),
        'is_today': day == timezone.localdate(),
        'appointments': [_appointment_payload(item) for item in appointments],
        'blocks': [_block_payload(item) for item in blocks],
    })


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def day_availability(request):
    staff_id = request.POST.get('staff_id') or request.GET.get('staff')
    day = parse_date(request.POST.get('date') or request.GET.get('date') or '')
    staff = StaffMember.objects.filter(pk=staff_id, active=True).first()
    if not staff or not day:
        if request.method == 'GET':
            return _private_json({'ok': False, 'error': 'invalid_request'}, status=400)
        return redirect('/verwaltung/kalender/?notice=hours-error')

    if request.method == 'GET':
        return _private_json({'ok': True, **_payload(staff, day)})

    action = request.POST.get('action') or 'save'
    if action == 'reset':
        DailyAvailabilityOverride.objects.filter(staff=staff, date=day).delete()
        return _calendar_redirect(staff.pk, day)

    closed = request.POST.get('closed') == 'on'
    start_1 = parse_time(request.POST.get('start_1') or '')
    end_1 = parse_time(request.POST.get('end_1') or '')
    start_2 = parse_time(request.POST.get('start_2') or '')
    end_2 = parse_time(request.POST.get('end_2') or '')

    if not closed:
        if not start_1 or not end_1 or not _is_quarter(start_1) or not _is_quarter(end_1):
            return _calendar_redirect(staff.pk, day, 'hours-error')
        if bool(start_2) != bool(end_2):
            return _calendar_redirect(staff.pk, day, 'hours-error')
        if start_2 and (not _is_quarter(start_2) or not _is_quarter(end_2)):
            return _calendar_redirect(staff.pk, day, 'hours-error')
    else:
        start_1 = end_1 = start_2 = end_2 = None

    override, _created = DailyAvailabilityOverride.objects.get_or_create(staff=staff, date=day)
    override.closed = closed
    override.start_time_1 = start_1
    override.end_time_1 = end_1
    override.start_time_2 = start_2
    override.end_time_2 = end_2
    try:
        override.full_clean()
    except ValidationError:
        return _calendar_redirect(staff.pk, day, 'hours-error')
    override.save()
    return _calendar_redirect(staff.pk, day)
