from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods
from datetime import datetime

from .models import BlockedPeriod, StaffMember
from . import views


def _local_dt(day, value):
    parsed_day = parse_date(day or '')
    parsed_time = parse_time(value or '')
    if not parsed_day or not parsed_time:
        return None
    return timezone.make_aware(
        datetime.combine(parsed_day, parsed_time),
        timezone.get_current_timezone(),
    )


def _scope_prefix(scope, service_id=None):
    if scope == 'all':
        return '[ALL]'
    if scope == 'service' and service_id:
        return f'[SERVICE:{service_id}]'
    return '[STAFF]'


def _calendar_url(*, day, view='day', staff_id=None, notice=None, focus_block=None):
    params = [f'date={day.isoformat()}', f'cal_view={view if view in {"day", "week"} else "day"}']
    if staff_id:
        params.append(f'staff={staff_id}')
    if notice:
        params.append(f'notice={notice}')
    if focus_block:
        params.append(f'focus_block={focus_block}')
    return '/verwaltung/kalender/?' + '&'.join(params)


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def dashboard_proxy(request):
    staff_qs = StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name')

    if request.method == 'POST' and request.POST.get('action') == 'add_calendar_note':
        selected_id = request.POST.get('staff_id') or request.GET.get('staff')
        selected_staff = staff_qs.filter(pk=selected_id).first() if selected_id else staff_qs.first()
        if not selected_staff:
            return redirect('/verwaltung/kalender/?notice=note-error')

        starts_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_start'))
        ends_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_end'))
        return_view = request.POST.get('return_view') or 'day'
        if not starts_at or not ends_at or ends_at <= starts_at:
            fallback_day = parse_date(request.POST.get('return_date') or '') or timezone.localdate()
            return redirect(_calendar_url(
                day=fallback_day,
                view=return_view,
                staff_id=selected_staff.pk,
                notice='note-error',
            ))

        text = (request.POST.get('note_text') or '').strip()[:120]
        scope = request.POST.get('note_scope') or 'all'
        service_id = request.POST.get('note_service_id') or None
        is_blocked = request.POST.get('note_blocked') == 'on'
        prefix = '[BLOCKNOTE]' if is_blocked else '[NOTE]'
        reason = f'{prefix}{_scope_prefix(scope, service_id)} {text or ("Gesperrt" if is_blocked else "Notiz")}'[:160]

        if scope == 'staff':
            targets = staff_qs.filter(pk=selected_staff.pk)
        elif scope == 'service' and service_id:
            targets = staff_qs.filter(services__pk=service_id).distinct()
        else:
            targets = staff_qs

        created_for_selected = None
        first_created = None
        for member in targets:
            item = BlockedPeriod.objects.create(
                staff=member,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=reason,
            )
            if first_created is None:
                first_created = item
            if member.pk == selected_staff.pk:
                created_for_selected = item

        focus = created_for_selected or first_created
        if not focus:
            return redirect(_calendar_url(
                day=starts_at.date(),
                view=return_view,
                staff_id=selected_staff.pk,
                notice='note-error',
            ))

        # Always return to the exact date of the saved entry. This avoids the old
        # situation where the success notice was shown on a different calendar day.
        return redirect(_calendar_url(
            day=timezone.localtime(focus.starts_at).date(),
            view=return_view,
            staff_id=focus.staff_id,
            notice='block' if is_blocked else 'note',
            focus_block=focus.pk,
        ))

    if request.method == 'POST' and request.POST.get('action') == 'add_block':
        selected_id = request.POST.get('staff_id') or request.GET.get('staff')
        selected_staff = staff_qs.filter(pk=selected_id).first() if selected_id else staff_qs.first()
        if not selected_staff:
            return redirect('/verwaltung/einstellungen/?notice=block-error')

        starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
        ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
        if not starts_at or not ends_at or ends_at <= starts_at:
            return redirect(f'/verwaltung/einstellungen/?staff={selected_staff.pk}&notice=block-error')

        item = BlockedPeriod.objects.create(
            staff=selected_staff,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=(request.POST.get('block_reason') or 'Gesperrt').strip()[:160],
        )
        return redirect(_calendar_url(
            day=timezone.localtime(item.starts_at).date(),
            view='day',
            staff_id=item.staff_id,
            notice='block',
            focus_block=item.pk,
        ))

    # If a freshly-created block is being focused, make the requested calendar date
    # authoritative from the stored record itself.
    if request.method == 'GET' and request.GET.get('focus_block'):
        block = BlockedPeriod.objects.filter(pk=request.GET.get('focus_block')).select_related('staff').first()
        if block:
            block_day = timezone.localtime(block.starts_at).date()
            requested_day = parse_date(request.GET.get('date') or '')
            requested_staff = request.GET.get('staff')
            if requested_day != block_day or str(requested_staff or '') != str(block.staff_id):
                return redirect(_calendar_url(
                    day=block_day,
                    view=request.GET.get('cal_view') or 'day',
                    staff_id=block.staff_id,
                    notice=request.GET.get('notice') or 'block',
                    focus_block=block.pk,
                ))

    return views.dashboard(request)
