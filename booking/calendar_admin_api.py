from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from .models import DailyAvailabilityOverride, StaffMember
from .services import effective_working_ranges


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


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def day_availability(request):
    staff_id = request.POST.get('staff_id') or request.GET.get('staff')
    day = parse_date(request.POST.get('date') or request.GET.get('date') or '')
    staff = StaffMember.objects.filter(pk=staff_id, active=True).first()
    if not staff or not day:
        if request.method == 'GET':
            return JsonResponse({'ok': False, 'error': 'invalid_request'}, status=400)
        return redirect('/verwaltung/kalender/?notice=hours-error')

    if request.method == 'GET':
        response = JsonResponse({'ok': True, **_payload(staff, day)})
        response['Cache-Control'] = 'private, no-store, max-age=0'
        return response

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
