import json
import re
from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.html import escape
from django.views.decorators.http import require_http_methods

from .models import BlockedPeriod, Service, StaffMember
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


def _targets_for_scope(staff_qs, selected_staff, scope, service_id=None):
    if scope == 'staff':
        return staff_qs.filter(pk=selected_staff.pk)
    if scope == 'service' and service_id:
        return staff_qs.filter(services__pk=service_id).distinct()
    return staff_qs


def _create_scoped_periods(*, staff_qs, selected_staff, starts_at, ends_at, reason, scope, service_id=None):
    targets = _targets_for_scope(staff_qs, selected_staff, scope, service_id)
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
    return created_for_selected or first_created


def _polish_admin_response(response, *, selected_staff_id=None, calendar_day=None, focus_block=None):
    content_type = response.get('Content-Type', '')
    if response.status_code != 200 or 'text/html' not in content_type:
        return response

    try:
        html = response.content.decode(response.charset or 'utf-8')
    except (AttributeError, UnicodeDecodeError):
        return response

    html = html.replace('/static/booking/logo.png', PREV_LOGO_URL)

    # Replace the old combined Note/Block action with two genuinely separate actions.
    old_fab = '<button type="button" data-open-note><span>Notiz hinzufügen / Zeitenfenster blockieren</span><b>✎</b></button>'
    new_fab = (
        '<button type="button" data-open-block><span>Zeitraum blockieren</span><b>⛔</b></button>'
        '<button type="button" data-open-note><span>Notiz hinzufügen</span><b>✎</b></button>'
    )
    html = html.replace(old_fab, new_fab)

    csrf_match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    csrf_value = csrf_match.group(1) if csrf_match else ''
    day_value = (calendar_day or timezone.localdate()).isoformat()
    staff_value = str(selected_staff_id or '')

    service_options = ['<option value="">Dienstleistung auswählen</option>']
    for service in Service.objects.filter(active=True).order_by('sort_order', 'name'):
        service_options.append(f'<option value="{service.pk}">{escape(service.name)}</option>')
    service_options_html = ''.join(service_options)

    block_modal = f"""
<div class="sb-modal" data-modal="block" aria-hidden="true">
  <div class="sb-modal-card sb-form-sheet">
    <div class="sb-sheet-head"><button type="button" data-close-modal>×</button><strong>Zeitraum blockieren</strong><span></span></div>
    <div class="sb-sheet-section-title">Details</div>
    <form method="post" class="sb-sheet-form" data-calendar-block-form>
      <input type="hidden" name="csrfmiddlewaretoken" value="{escape(csrf_value)}">
      <input type="hidden" name="action" value="add_calendar_block">
      <input type="hidden" name="staff_id" value="{escape(staff_value)}">
      <input type="hidden" name="return_view" value="day">
      <label class="sb-form-row"><span class="sb-row-icon">▣</span><div><small>Startdatum und -uhrzeit</small><input type="date" name="block_date" value="{day_value}" required><input type="time" name="block_start" step="900" required></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">▣</span><div><small>Enddatum und -uhrzeit</small><input type="time" name="block_end" step="900" required></div></label>
      <div class="sb-explicit-block-note"><strong>Zeitraum wird blockiert</strong><span>Online-Buchungen sind in diesem Zeitraum nicht möglich.</span></div>
      <div class="sb-sheet-section-title inner">Anwendung der Sperrzeit</div>
      <div class="sb-scope-tabs">
        <label><input type="radio" name="block_scope" value="all" checked><span>Für alle<br>anwenden</span></label>
        <label><input type="radio" name="block_scope" value="staff"><span>Für Dienstleister<br>anwenden</span></label>
        <label><input type="radio" name="block_scope" value="service"><span>Für Dienstleistung<br>anwenden</span></label>
      </div>
      <label class="sb-form-row sb-block-service-row"><span class="sb-row-icon">◒</span><div><small>Dienstleistung</small><select name="block_service_id">{service_options_html}</select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">☷</span><div><small>Grund / Notiz</small><input type="text" name="block_text" maxlength="120" placeholder="z. B. Pause"></div></label>
      <button type="submit" class="sb-sheet-save">Zeitraum blockieren</button>
    </form>
  </div>
</div>
"""

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
.sb-modal[data-modal="note"] .sb-block-toggle{{display:none!important}}
.sb-explicit-block-note{{margin:14px 0;padding:13px 14px;border:1px solid #d9c08e;border-radius:12px;background:#fbf3df;display:grid;gap:4px;color:#5b4325}}
.sb-explicit-block-note strong{{font-size:13px}}.sb-explicit-block-note span{{font-size:10px;color:#7d6545}}
.sb-block-service-row{{display:none}}.sb-block-service-row.is-visible{{display:grid}}
</style>
<script>
(function(){{
  const focusTime = {json.dumps(focus_time)};
  const logoUrl = {json.dumps(PREV_LOGO_URL)};

  document.querySelectorAll('.sb-drawer-brand img, .brand-logo').forEach((img) => {{
    img.src = logoUrl;
    img.removeAttribute('srcset');
  }});

  function openBlockModal() {{
    const modal = document.querySelector('[data-modal="block"]');
    if (!modal) return;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
  }}

  document.querySelectorAll('[data-open-block]').forEach((button) => button.addEventListener('click', openBlockModal));

  const blockModal = document.querySelector('[data-modal="block"]');
  if (blockModal) {{
    blockModal.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', () => {{
      blockModal.classList.remove('is-open');
      blockModal.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('sb-modal-open');
    }}));
    blockModal.addEventListener('click', (event) => {{
      if (event.target === blockModal) {{
        blockModal.classList.remove('is-open');
        blockModal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('sb-modal-open');
      }}
    }});

    const serviceRow = blockModal.querySelector('.sb-block-service-row');
    blockModal.querySelectorAll('input[name="block_scope"]').forEach((radio) => radio.addEventListener('change', () => {{
      if (serviceRow) serviceRow.classList.toggle('is-visible', radio.checked && radio.value === 'service');
    }}));
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
    html = html.replace('</body>', block_modal + enhancement + '</body>')
    response.content = html.encode(response.charset or 'utf-8')
    return response


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def dashboard_proxy(request):
    staff_qs = StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name')
    selected_id = request.POST.get('staff_id') or request.GET.get('staff')
    selected_staff = staff_qs.filter(pk=selected_id).first() if selected_id else staff_qs.first()

    if request.method == 'POST' and request.POST.get('action') == 'add_calendar_block':
        if not selected_staff:
            return redirect('/verwaltung/kalender/?notice=block-error')

        starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
        ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
        if not starts_at or not ends_at or ends_at <= starts_at:
            fallback_day = parse_date(request.POST.get('block_date') or '') or timezone.localdate()
            return redirect(_calendar_url(
                day=fallback_day,
                view='day',
                staff_id=selected_staff.pk,
                notice='block-error',
            ))

        # Server-side enforcement: admin blocking always follows 15-minute boundaries.
        if starts_at.minute % 15 or ends_at.minute % 15:
            return redirect(_calendar_url(
                day=timezone.localtime(starts_at).date(),
                view='day',
                staff_id=selected_staff.pk,
                notice='block-error',
            ))

        scope = request.POST.get('block_scope') or 'all'
        service_id = request.POST.get('block_service_id') or None
        text = (request.POST.get('block_text') or '').strip()[:120]
        reason = f'[BLOCKNOTE]{_scope_prefix(scope, service_id)} {text or "Gesperrt"}'[:160]
        focus = _create_scoped_periods(
            staff_qs=staff_qs,
            selected_staff=selected_staff,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=reason,
            scope=scope,
            service_id=service_id,
        )
        if not focus:
            return redirect(_calendar_url(
                day=timezone.localtime(starts_at).date(),
                view='day',
                staff_id=selected_staff.pk,
                notice='block-error',
            ))
        return redirect(_calendar_url(
            day=timezone.localtime(focus.starts_at).date(),
            view='day',
            staff_id=focus.staff_id,
            notice='block',
            focus_block=focus.pk,
        ))

    if request.method == 'POST' and request.POST.get('action') == 'add_calendar_note':
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
        # Notes are now always notes. Blocking has its own dedicated form/action.
        reason = f'[NOTE]{_scope_prefix(scope, service_id)} {text or "Notiz"}'[:160]
        focus = _create_scoped_periods(
            staff_qs=staff_qs,
            selected_staff=selected_staff,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=reason,
            scope=scope,
            service_id=service_id,
        )
        if not focus:
            return redirect(_calendar_url(
                day=timezone.localtime(starts_at).date(),
                view=return_view,
                staff_id=selected_staff.pk,
                notice='note-error',
            ))
        return redirect(_calendar_url(
            day=timezone.localtime(focus.starts_at).date(),
            view=return_view,
            staff_id=focus.staff_id,
            notice='note',
            focus_block=focus.pk,
        ))

    if request.method == 'POST' and request.POST.get('action') == 'add_block':
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
    calendar_day = parse_date(request.GET.get('date') or '') or timezone.localdate()
    return _polish_admin_response(
        response,
        selected_staff_id=selected_staff.pk if selected_staff else None,
        calendar_day=calendar_day,
        focus_block=focus_block,
    )