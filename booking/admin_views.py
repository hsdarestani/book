import json
from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from .models import BlockedPeriod, StaffMember
from . import views


PREV_LOGO_URL = 'https://a-esthetic.de/wp-content/uploads/prev.png'


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


def _polish_admin_response(response, focus_block=None):
    content_type = response.get('Content-Type', '')
    if response.status_code != 200 or 'text/html' not in content_type:
        return response

    try:
        html = response.content.decode(response.charset or 'utf-8')
    except (AttributeError, UnicodeDecodeError):
        return response

    # The old static logo was too dark in the mobile drawer/top bar. Use the same
    # visual that is used in the booking confirmation email/brand presentation.
    html = html.replace('/static/booking/logo.png', PREV_LOGO_URL)

    focus_time = ''
    if focus_block:
        item = BlockedPeriod.objects.filter(pk=focus_block).first()
        if item:
            start = timezone.localtime(item.starts_at).strftime('%H:%M')
            end = timezone.localtime(item.ends_at).strftime('%H:%M')
            focus_time = f'{start}–{end}'

    enhancement = f"""
<style>
.sb-calendar-block.is-focused-block{{outline:3px solid #8d652e!important;outline-offset:2px!important;box-shadow:0 8px 24px rgba(72,49,20,.28)!important;z-index:8!important}}
.sb-force-block-hint{{display:block;color:#87632f!important;font-weight:700!important;margin-top:2px}}
</style>
<script>
(function(){{
  const focusTime = {json.dumps(focus_time)};
  const logoUrl = {json.dumps(PREV_LOGO_URL)};

  document.querySelectorAll('.sb-drawer-brand img, .brand-logo').forEach((img) => {{
    img.src = logoUrl;
    img.removeAttribute('srcset');
  }});

  const noteModal = document.querySelector('[data-modal="note"]');
  const noteForm = noteModal ? noteModal.querySelector('form') : null;
  let forceField = noteForm ? noteForm.querySelector('input[name="force_block"]') : null;
  if (noteForm && !forceField) {{
    forceField = document.createElement('input');
    forceField.type = 'hidden';
    forceField.name = 'force_block';
    forceField.value = '';
    noteForm.appendChild(forceField);
  }}

  const blockedCheckbox = noteForm ? noteForm.querySelector('input[name="note_blocked"]') : null;
  const modalTitle = noteModal ? noteModal.querySelector('.sb-sheet-head strong') : null;
  const toggleCopy = noteModal ? noteModal.querySelector('.sb-block-toggle span') : null;

  function setNoteMode(blocking) {{
    if (forceField) forceField.value = blocking ? '1' : '';
    if (blockedCheckbox) {{
      blockedCheckbox.checked = blocking;
      blockedCheckbox.disabled = blocking;
    }}
    if (modalTitle) modalTitle.textContent = blocking ? 'Zeitraum blockieren' : 'Neue Notiz';
    if (toggleCopy) {{
      toggleCopy.textContent = blocking
        ? 'Dieser Zeitraum wird sicher für Online-Buchungen blockiert.'
        : 'Wenn aktiviert, wird der Zeitraum für Online-Buchungen blockiert.';
      toggleCopy.classList.toggle('sb-force-block-hint', blocking);
    }}
  }}

  // Existing note buttons keep the normal note flow.
  document.querySelectorAll('[data-open-note]').forEach((button) => {{
    button.addEventListener('click', () => setNoteMode(false));
  }});

  // Split the combined FAB action into two explicit actions. The block action sends
  // force_block=1, so it no longer depends on a custom checkbox/toggle implementation.
  const fabActions = document.querySelector('[data-fab-actions]');
  const noteButton = fabActions ? fabActions.querySelector('[data-open-note]') : null;
  if (fabActions && noteButton && !fabActions.querySelector('[data-open-block]')) {{
    const noteLabel = noteButton.querySelector('span');
    if (noteLabel) noteLabel.textContent = 'Notiz hinzufügen';

    const blockButton = noteButton.cloneNode(true);
    blockButton.setAttribute('data-open-block', '1');
    const blockLabel = blockButton.querySelector('span');
    const blockIcon = blockButton.querySelector('b');
    if (blockLabel) blockLabel.textContent = 'Zeitraum blockieren';
    if (blockIcon) blockIcon.textContent = '⛔';
    blockButton.addEventListener('click', () => setNoteMode(true));
    fabActions.insertBefore(blockButton, noteButton);
  }}

  if (focusTime) {{
    window.addEventListener('load', () => {{
      window.setTimeout(() => {{
        const target = [...document.querySelectorAll('.sb-calendar-block')].find((block) => {{
          const time = block.querySelector('small');
          return time && time.textContent.trim() === focusTime;
        }});
        if (target) {{
          target.classList.add('is-focused-block');
          target.scrollIntoView({{behavior:'smooth', block:'center'}});
        }}
      }}, 180);
    }}, {{once:true}});
  }}
}})();
</script>
"""
    html = html.replace('</body>', enhancement + '</body>')
    response.content = html.encode(response.charset or 'utf-8')
    return response


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
        is_blocked = request.POST.get('force_block') == '1' or request.POST.get('note_blocked') == 'on'
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

    focus_block = request.GET.get('focus_block')
    if request.method == 'GET' and focus_block:
        block = BlockedPeriod.objects.filter(pk=focus_block).select_related('staff').first()
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

    response = views.dashboard(request)
    return _polish_admin_response(response, focus_block=focus_block)
