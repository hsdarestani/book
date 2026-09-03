import json
import re
from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.utils.html import escape
from django.views.decorators.http import require_http_methods

from .models import Appointment, BlockedPeriod, Customer, Service, StaffMember
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


def _is_quarter(value):
    return bool(value) and value.minute % 15 == 0


def _scope_prefix(scope, service_id=None):
    if scope == 'all':
        return '[ALL]'
    if scope == 'service' and service_id:
        return f'[SERVICE:{service_id}]'
    return '[STAFF]'


def _scope_from_reason(reason):
    value = reason or ''
    if '[ALL]' in value:
        return 'all', None
    match = re.search(r'\[SERVICE:(\d+)\]', value)
    if match:
        return 'service', match.group(1)
    return 'staff', None


def _kind_from_reason(reason):
    return 'note' if (reason or '').startswith('[NOTE]') else 'block'


def _clean_reason(reason):
    return views._clean_calendar_reason(reason)


def _calendar_url(*, day, view='day', staff_id=None, notice=None, focus_block=None, focus_appointment=None):
    params = [f'date={day.isoformat()}', f'cal_view={view if view in {"day", "week"} else "day"}']
    if staff_id:
        params.append(f'staff={staff_id}')
    if notice:
        params.append(f'notice={notice}')
    if focus_block:
        params.append(f'focus_block={focus_block}')
    if focus_appointment:
        params.append(f'focus_appointment={focus_appointment}')
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
        first_created = first_created or item
        if member.pk == selected_staff.pk:
            created_for_selected = item
    return created_for_selected or first_created


def _period_group(item):
    scope, _ = _scope_from_reason(item.reason)
    if scope in {'all', 'service'}:
        return BlockedPeriod.objects.filter(
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            reason=item.reason,
        )
    return BlockedPeriod.objects.filter(pk=item.pk)


def _normalize_calendar_css(html):
    """Normalize decimal commas produced by de-DE localization in inline CSS."""
    return re.sub(
        r'(?P<prop>\b(?:top|height)):(?P<int>\d+),(?P<frac>\d+)%',
        r'\g<prop>:\g<int>.\g<frac>%',
        html,
    )


def _json_for_script(value):
    return (
        json.dumps(value, ensure_ascii=False)
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
    )


def _calendar_range(calendar_day, calendar_view):
    if calendar_view == 'week':
        start_day = calendar_day - timedelta(days=calendar_day.weekday())
        end_day = start_day + timedelta(days=7)
    else:
        start_day = calendar_day
        end_day = start_day + timedelta(days=1)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start_day, datetime.min.time()), tz)
    end_dt = timezone.make_aware(datetime.combine(end_day, datetime.min.time()), tz)
    return start_dt, end_dt


def _appointment_payload(item):
    local_start = timezone.localtime(item.starts_at)
    return {
        'id': item.pk,
        'service_id': item.service_id,
        'staff_id': item.staff_id,
        'customer_id': item.customer_id,
        'date': local_start.date().isoformat(),
        'time': local_start.strftime('%H:%M'),
        'status': item.status,
        'customer_name': item.customer.full_name,
        'service_name': item.service.name,
        'staff_name': item.staff.display_name,
    }


def _block_payload(item):
    local_start = timezone.localtime(item.starts_at)
    local_end = timezone.localtime(item.ends_at)
    scope, service_id = _scope_from_reason(item.reason)
    return {
        'id': item.pk,
        'staff_id': item.staff_id,
        'date': local_start.date().isoformat(),
        'start': local_start.strftime('%H:%M'),
        'end': local_end.strftime('%H:%M'),
        'kind': _kind_from_reason(item.reason),
        'scope': scope,
        'service_id': service_id or '',
        'text': _clean_reason(item.reason),
    }


def _replace_notice(html, notice):
    messages = {
        'block-updated': 'Sperrzeit / Notiz wurde aktualisiert.',
        'appointment-updated': 'Termin wurde aktualisiert.',
        'appointment-deleted': 'Termin wurde gelöscht.',
        'appointment-edit-error': 'Die Terminänderung ist nicht möglich. Bitte Zeitraum, Behandlung und Behandler prüfen.',
    }
    message = messages.get(notice)
    if not message:
        return html
    pattern = re.compile(r'(<div class="admin-notice[^>]*>)(.*?)(</div>)', re.S)
    return pattern.sub(lambda match: f'{match.group(1)}{escape(message)}{match.group(3)}', html, count=1)


def _polish_admin_response(
    response,
    *,
    selected_staff_id=None,
    calendar_day=None,
    calendar_view='day',
    focus_block=None,
    focus_appointment=None,
    notice=None,
):
    content_type = response.get('Content-Type', '')
    if response.status_code != 200 or 'text/html' not in content_type:
        return response

    try:
        html = response.content.decode(response.charset or 'utf-8')
    except (AttributeError, UnicodeDecodeError):
        return response

    html = _normalize_calendar_css(html)
    html = html.replace('/static/booking/logo.png', PREV_LOGO_URL)
    html = _replace_notice(html, notice)

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

    services = list(Service.objects.filter(active=True).order_by('sort_order', 'name'))
    staff_members = list(StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name'))
    customers = list(Customer.objects.order_by('last_name', 'first_name')[:1000])

    service_options = ['<option value="">Dienstleistung auswählen</option>']
    for service in services:
        service_options.append(f'<option value="{service.pk}">{escape(service.name)}</option>')
    service_options_html = ''.join(service_options)

    staff_options = ''.join(
        f'<option value="{member.pk}">{escape(member.display_name)}</option>' for member in staff_members
    )
    customer_options = ''.join(
        f'<option value="{customer.pk}">{escape(customer.full_name)} · {escape(customer.email)}</option>'
        for customer in customers
    )
    status_options = ''.join(
        f'<option value="{value}">{escape(label)}</option>' for value, label in Appointment.STATUS
    )

    start_dt, end_dt = _calendar_range(calendar_day or timezone.localdate(), calendar_view)
    visible_appointments = list(
        Appointment.objects.filter(
            staff_id=selected_staff_id,
            starts_at__lt=end_dt,
            ends_at__gt=start_dt,
        )
        .exclude(status='cancelled')
        .select_related('customer', 'service', 'staff')
        .order_by('starts_at')
    ) if selected_staff_id else []

    appointment_map = {str(item.pk): _appointment_payload(item) for item in visible_appointments}
    for item in (
        Appointment.objects.filter(starts_at__gte=timezone.now())
        .select_related('customer', 'service', 'staff')
        .order_by('starts_at')[:120]
    ):
        appointment_map.setdefault(str(item.pk), _appointment_payload(item))

    visible_blocks = list(
        BlockedPeriod.objects.filter(
            staff_id=selected_staff_id,
            starts_at__lt=end_dt,
            ends_at__gt=start_dt,
        ).select_related('staff').order_by('starts_at')
    ) if selected_staff_id else []
    block_map = {str(item.pk): _block_payload(item) for item in visible_blocks}
    for item in (
        BlockedPeriod.objects.filter(ends_at__gte=timezone.now())
        .select_related('staff')
        .order_by('starts_at')[:200]
    ):
        block_map.setdefault(str(item.pk), _block_payload(item))

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

    edit_block_modal = f"""
<div class="sb-modal" data-modal="calendar-item-edit" aria-hidden="true">
  <div class="sb-modal-card sb-form-sheet">
    <div class="sb-sheet-head"><button type="button" data-close-modal>×</button><strong data-edit-block-title>Sperrzeit bearbeiten</strong><span></span></div>
    <div class="sb-sheet-section-title">Details</div>
    <form method="post" class="sb-sheet-form" data-calendar-item-edit-form>
      <input type="hidden" name="csrfmiddlewaretoken" value="{escape(csrf_value)}">
      <input type="hidden" name="block_id">
      <input type="hidden" name="staff_id" value="{escape(staff_value)}">
      <input type="hidden" name="return_view" value="{escape(calendar_view)}">
      <label class="sb-form-row"><span class="sb-row-icon">◉</span><div><small>Typ</small><select name="item_kind"><option value="block">Zeitraum blockieren</option><option value="note">Notiz</option></select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">▣</span><div><small>Datum</small><input type="date" name="item_date" required></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">◷</span><div><small>Von / Bis</small><div class="sb-inline-times"><input type="time" name="item_start" step="900" required><span>–</span><input type="time" name="item_end" step="900" required></div></div></label>
      <div class="sb-sheet-section-title inner">Anwendung</div>
      <div class="sb-scope-tabs" data-edit-block-scopes>
        <label><input type="radio" name="item_scope" value="all"><span>Für alle<br>anwenden</span></label>
        <label><input type="radio" name="item_scope" value="staff"><span>Für Dienstleister<br>anwenden</span></label>
        <label><input type="radio" name="item_scope" value="service"><span>Für Dienstleistung<br>anwenden</span></label>
      </div>
      <label class="sb-form-row sb-edit-service-row"><span class="sb-row-icon">◒</span><div><small>Dienstleistung</small><select name="item_service_id">{service_options_html}</select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">☷</span><div><small>Text / Grund</small><input type="text" name="item_text" maxlength="120"></div></label>
      <div class="sb-edit-actions">
        <button type="submit" name="action" value="edit_calendar_item" class="sb-sheet-save">Änderungen speichern</button>
        <button type="submit" name="action" value="delete_calendar_item" formnovalidate class="sb-danger-submit" data-confirm-delete="Diesen Kalendereintrag wirklich löschen?">Eintrag löschen</button>
      </div>
    </form>
  </div>
</div>
"""

    edit_appointment_modal = f"""
<div class="sb-modal" data-modal="appointment-edit" aria-hidden="true">
  <div class="sb-modal-card sb-form-sheet">
    <div class="sb-sheet-head"><button type="button" data-close-modal>×</button><strong>Termin bearbeiten</strong><span></span></div>
    <div class="sb-sheet-section-title">Buchungsinformationen</div>
    <form method="post" class="sb-sheet-form" data-appointment-edit-form>
      <input type="hidden" name="csrfmiddlewaretoken" value="{escape(csrf_value)}">
      <input type="hidden" name="appointment_id">
      <input type="hidden" name="return_view" value="{escape(calendar_view)}">
      <label class="sb-form-row"><span class="sb-row-icon">◒</span><div><small>Dienstleistung</small><select name="service_id" required>{service_options_html}</select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">♟</span><div><small>Dienstleister</small><select name="appointment_staff_id" required>{staff_options}</select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">♙</span><div><small>Kunde</small><select name="customer_id" required>{customer_options}</select></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">▣</span><div><small>Datum</small><input type="date" name="appointment_date" required></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">◷</span><div><small>Uhrzeit</small><input type="time" name="appointment_time" step="900" required></div></label>
      <label class="sb-form-row"><span class="sb-row-icon">✓</span><div><small>Status</small><select name="status">{status_options}</select></div></label>
      <div class="sb-edit-actions">
        <button type="submit" name="action" value="edit_appointment" class="sb-sheet-save">Änderungen speichern</button>
        <button type="submit" name="action" value="delete_appointment" formnovalidate class="sb-danger-submit" data-confirm-delete="Diesen Termin wirklich endgültig löschen?">Termin löschen</button>
      </div>
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
.sb-calendar-block.is-focused-block,.sb-calendar-event.is-focused-appointment{{outline:3px solid #8d652e!important;outline-offset:2px!important;box-shadow:0 8px 24px rgba(72,49,20,.28)!important;z-index:8!important}}
.sb-modal[data-modal="note"] .sb-block-toggle{{display:none!important}}
.sb-explicit-block-note{{margin:14px 0;padding:13px 14px;border:1px solid #d9c08e;border-radius:12px;background:#fbf3df;display:grid;gap:4px;color:#5b4325}}
.sb-explicit-block-note strong{{font-size:13px}}.sb-explicit-block-note span{{font-size:10px;color:#7d6545}}
.sb-block-service-row,.sb-edit-service-row{{display:none}}.sb-block-service-row.is-visible,.sb-edit-service-row.is-visible{{display:grid}}
.sb-calendar-block,.sb-calendar-event{{cursor:pointer}}
.sb-calendar-event{{appearance:none;text-align:left;font-family:inherit}}
.sb-event-menu{{position:absolute;right:4px;top:4px;width:24px;height:24px;border:0;border-radius:50%;background:rgba(255,255,255,.76);color:#4b3a26;font-weight:900;cursor:pointer;display:grid;place-items:center;z-index:10}}
.sb-block-item-edit,.sb-row-edit{{appearance:none;border:1px solid #ded5c8;background:#fff;border-radius:9px;min-width:34px;height:34px;cursor:pointer;font-size:18px;line-height:1}}
.status-form{{display:flex!important;align-items:center;gap:6px}}
.status-form select{{min-width:0;flex:1}}
.sb-inline-times{{display:grid!important;grid-template-columns:1fr auto 1fr!important;gap:8px!important;align-items:center!important}}
.sb-edit-actions{{display:grid;gap:10px;margin-top:18px}}
.sb-edit-actions .sb-sheet-save{{margin-top:0}}
.sb-danger-submit{{appearance:none;width:100%;border:1px solid #e1b9b5;border-radius:12px;padding:13px 18px;background:#fff7f6;color:#a13f38;font:800 13px inherit;cursor:pointer}}
@media(max-width:760px){{.sb-row-edit{{width:38px;min-width:38px}}}}
</style>
<script>
(function(){{
  const focusTime = {_json_for_script(focus_time)};
  const focusAppointment = {_json_for_script(str(focus_appointment or ''))};
  const logoUrl = {_json_for_script(PREV_LOGO_URL)};
  const visibleAppointmentIds = {_json_for_script([str(item.pk) for item in visible_appointments])};
  const appointments = {_json_for_script(appointment_map)};
  const blocks = {_json_for_script(block_map)};

  document.querySelectorAll('.sb-drawer-brand img, .brand-logo').forEach((img) => {{
    img.src = logoUrl;
    img.removeAttribute('srcset');
  }});

  function openModal(name) {{
    const modal = document.querySelector(`[data-modal="${{name}}"]`);
    if (!modal) return null;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
    return modal;
  }}
  function closeModal(modal) {{
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sb-modal-open');
  }}

  document.querySelectorAll('[data-modal] [data-close-modal]').forEach((button) => button.addEventListener('click', () => closeModal(button.closest('[data-modal]'))));
  document.querySelectorAll('[data-modal]').forEach((modal) => modal.addEventListener('click', (event) => {{ if (event.target === modal) closeModal(modal); }}));
  document.querySelectorAll('[data-confirm-delete]').forEach((button) => button.addEventListener('click', (event) => {{
    if (!window.confirm(button.dataset.confirmDelete || 'Wirklich löschen?')) event.preventDefault();
  }}));

  function openBlockModal() {{
    const modal = openModal('block');
    if (!modal) return;
    const dateInput = modal.querySelector('[name="block_date"]');
    if (dateInput && !dateInput.value) dateInput.value = {_json_for_script(day_value)};
  }}
  document.querySelectorAll('[data-open-block]').forEach((button) => button.addEventListener('click', openBlockModal));

  const blockModal = document.querySelector('[data-modal="block"]');
  if (blockModal) {{
    const serviceRow = blockModal.querySelector('.sb-block-service-row');
    blockModal.querySelectorAll('input[name="block_scope"]').forEach((radio) => radio.addEventListener('change', () => {{
      if (serviceRow) serviceRow.classList.toggle('is-visible', radio.checked && radio.value === 'service');
    }}));
  }}

  function openCalendarItemEditor(id) {{
    const data = blocks[String(id)];
    if (!data) return;
    const modal = openModal('calendar-item-edit');
    if (!modal) return;
    const form = modal.querySelector('[data-calendar-item-edit-form]');
    form.elements.block_id.value = data.id;
    form.elements.staff_id.value = data.staff_id;
    form.elements.item_kind.value = data.kind;
    form.elements.item_date.value = data.date;
    form.elements.item_start.value = data.start;
    form.elements.item_end.value = data.end;
    form.elements.item_text.value = data.text || '';
    form.elements.item_service_id.value = data.service_id || '';
    form.querySelectorAll('input[name="item_scope"]').forEach((radio) => {{ radio.checked = radio.value === data.scope; }});
    const serviceRow = form.querySelector('.sb-edit-service-row');
    serviceRow?.classList.toggle('is-visible', data.scope === 'service');
    modal.querySelector('[data-edit-block-title]').textContent = data.kind === 'note' ? 'Notiz bearbeiten' : 'Sperrzeit bearbeiten';
  }}

  document.querySelectorAll('[data-calendar-item-edit-form] input[name="item_scope"]').forEach((radio) => radio.addEventListener('change', () => {{
    const row = radio.closest('form')?.querySelector('.sb-edit-service-row');
    row?.classList.toggle('is-visible', radio.checked && radio.value === 'service');
  }}));

  document.querySelectorAll('.sb-calendar-block').forEach((node) => {{
    const id = node.querySelector('input[name="block_id"]')?.value;
    if (!id) return;
    node.dataset.editBlock = id;
    node.tabIndex = 0;
    node.setAttribute('role', 'button');
    node.querySelector('.sb-event-delete')?.remove();
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'sb-event-menu';
    menu.textContent = '⋮';
    menu.setAttribute('aria-label', 'Eintrag bearbeiten');
    menu.addEventListener('click', (event) => {{ event.stopPropagation(); openCalendarItemEditor(id); }});
    node.appendChild(menu);
    node.addEventListener('click', () => openCalendarItemEditor(id));
    node.addEventListener('keydown', (event) => {{ if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); openCalendarItemEditor(id); }} }});
  }});

  document.querySelectorAll('.block-item').forEach((node) => {{
    const id = node.querySelector('input[name="block_id"]')?.value;
    if (!id || !blocks[String(id)]) return;
    const edit = document.createElement('button');
    edit.type = 'button'; edit.className = 'sb-block-item-edit'; edit.textContent = '✎'; edit.setAttribute('aria-label', 'Sperrzeit bearbeiten');
    edit.addEventListener('click', (event) => {{ event.preventDefault(); event.stopPropagation(); openCalendarItemEditor(id); }});
    node.appendChild(edit);
  }});

  function openAppointmentEditor(id) {{
    const data = appointments[String(id)];
    if (!data) return;
    const modal = openModal('appointment-edit');
    if (!modal) return;
    const form = modal.querySelector('[data-appointment-edit-form]');
    form.elements.appointment_id.value = data.id;
    form.elements.service_id.value = data.service_id;
    form.elements.appointment_staff_id.value = data.staff_id;
    form.elements.customer_id.value = data.customer_id;
    form.elements.appointment_date.value = data.date;
    form.elements.appointment_time.value = data.time;
    form.elements.status.value = data.status;
  }}

  document.querySelectorAll('.sb-calendar-event').forEach((node, index) => {{
    const id = visibleAppointmentIds[index];
    if (!id) return;
    node.dataset.editAppointment = id;
    node.addEventListener('click', (event) => {{ event.preventDefault(); openAppointmentEditor(id); }});
  }});

  document.querySelectorAll('.status-form').forEach((form) => {{
    const id = form.querySelector('input[name="appointment_id"]')?.value;
    if (!id || !appointments[String(id)]) return;
    const edit = document.createElement('button');
    edit.type = 'button'; edit.className = 'sb-row-edit'; edit.textContent = '⋮'; edit.setAttribute('aria-label', 'Termin bearbeiten');
    edit.addEventListener('click', () => openAppointmentEditor(id));
    form.appendChild(edit);
  }});

  if (focusTime) {{
    window.addEventListener('load', () => window.setTimeout(() => {{
      const target = [...document.querySelectorAll('.sb-calendar-block')].find((block) => block.querySelector('small')?.textContent.trim() === focusTime);
      if (target) {{ target.classList.add('is-focused-block'); target.scrollIntoView({{behavior:'smooth', block:'center'}}); }}
    }}, 180), {{once:true}});
  }}
  if (focusAppointment) {{
    window.addEventListener('load', () => window.setTimeout(() => {{
      const target = document.querySelector(`.sb-calendar-event[data-edit-appointment="${{focusAppointment}}"]`);
      if (target) {{ target.classList.add('is-focused-appointment'); target.scrollIntoView({{behavior:'smooth', block:'center'}}); }}
    }}, 180), {{once:true}});
  }}
}})();
</script>
"""

    html = html.replace('</body>', block_modal + edit_block_modal + edit_appointment_modal + enhancement + '</body>')
    response.content = html.encode(response.charset or 'utf-8')
    return response


@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def dashboard_proxy(request):
    staff_qs = StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name')
    selected_id = request.POST.get('staff_id') or request.GET.get('staff')
    selected_staff = staff_qs.filter(pk=selected_id).first() if selected_id else staff_qs.first()
    action = request.POST.get('action') if request.method == 'POST' else None

    if request.method == 'POST' and action == 'add_calendar_block':
        if not selected_staff:
            return redirect('/verwaltung/kalender/?notice=block-error')
        starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
        ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
        if not starts_at or not ends_at or ends_at <= starts_at or not _is_quarter(starts_at) or not _is_quarter(ends_at):
            fallback_day = parse_date(request.POST.get('block_date') or '') or timezone.localdate()
            return redirect(_calendar_url(day=fallback_day, view='day', staff_id=selected_staff.pk, notice='block-error'))

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
            return redirect(_calendar_url(day=timezone.localtime(starts_at).date(), view='day', staff_id=selected_staff.pk, notice='block-error'))
        return redirect(_calendar_url(day=timezone.localtime(focus.starts_at).date(), view='day', staff_id=focus.staff_id, notice='block', focus_block=focus.pk))

    if request.method == 'POST' and action == 'add_calendar_note':
        if not selected_staff:
            return redirect('/verwaltung/kalender/?notice=note-error')
        starts_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_start'))
        ends_at = _local_dt(request.POST.get('note_date'), request.POST.get('note_end'))
        return_view = request.POST.get('return_view') or 'day'
        if not starts_at or not ends_at or ends_at <= starts_at or not _is_quarter(starts_at) or not _is_quarter(ends_at):
            fallback_day = parse_date(request.POST.get('return_date') or '') or timezone.localdate()
            return redirect(_calendar_url(day=fallback_day, view=return_view, staff_id=selected_staff.pk, notice='note-error'))

        text = (request.POST.get('note_text') or '').strip()[:120]
        scope = request.POST.get('note_scope') or 'all'
        service_id = request.POST.get('note_service_id') or None
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
            return redirect(_calendar_url(day=timezone.localtime(starts_at).date(), view=return_view, staff_id=selected_staff.pk, notice='note-error'))
        return redirect(_calendar_url(day=timezone.localtime(focus.starts_at).date(), view=return_view, staff_id=focus.staff_id, notice='note', focus_block=focus.pk))

    if request.method == 'POST' and action == 'edit_calendar_item':
        item = BlockedPeriod.objects.filter(pk=request.POST.get('block_id')).select_related('staff').first()
        if not item:
            return redirect('/verwaltung/kalender/?notice=block-error')
        starts_at = _local_dt(request.POST.get('item_date'), request.POST.get('item_start'))
        ends_at = _local_dt(request.POST.get('item_date'), request.POST.get('item_end'))
        if not starts_at or not ends_at or ends_at <= starts_at or not _is_quarter(starts_at) or not _is_quarter(ends_at):
            return redirect(_calendar_url(day=timezone.localtime(item.starts_at).date(), view=request.POST.get('return_view') or 'day', staff_id=item.staff_id, notice='block-error', focus_block=item.pk))

        scope = request.POST.get('item_scope') or 'staff'
        service_id = request.POST.get('item_service_id') or None
        if scope == 'service' and not Service.objects.filter(pk=service_id, active=True).exists():
            return redirect(_calendar_url(day=timezone.localtime(item.starts_at).date(), view=request.POST.get('return_view') or 'day', staff_id=item.staff_id, notice='block-error', focus_block=item.pk))
        kind = request.POST.get('item_kind') if request.POST.get('item_kind') in {'block', 'note'} else _kind_from_reason(item.reason)
        text = (request.POST.get('item_text') or '').strip()[:120]
        prefix = '[NOTE]' if kind == 'note' else '[BLOCKNOTE]'
        reason = f'{prefix}{_scope_prefix(scope, service_id)} {text or ("Notiz" if kind == "note" else "Gesperrt")}'[:160]
        original_group = _period_group(item)
        selected_for_new = staff_qs.filter(pk=request.POST.get('staff_id')).first() or item.staff
        with transaction.atomic():
            original_group.delete()
            focus = _create_scoped_periods(
                staff_qs=staff_qs,
                selected_staff=selected_for_new,
                starts_at=starts_at,
                ends_at=ends_at,
                reason=reason,
                scope=scope,
                service_id=service_id,
            )
        return redirect(_calendar_url(day=timezone.localtime(focus.starts_at).date(), view=request.POST.get('return_view') or 'day', staff_id=focus.staff_id, notice='block-updated', focus_block=focus.pk))

    if request.method == 'POST' and action == 'delete_calendar_item':
        item = BlockedPeriod.objects.filter(pk=request.POST.get('block_id')).select_related('staff').first()
        if not item:
            return redirect('/verwaltung/kalender/?notice=block-deleted')
        day = timezone.localtime(item.starts_at).date()
        staff_id = item.staff_id
        _period_group(item).delete()
        return redirect(_calendar_url(day=day, view=request.POST.get('return_view') or 'day', staff_id=staff_id, notice='block-deleted'))

    if request.method == 'POST' and action == 'edit_appointment':
        appointment = Appointment.objects.filter(pk=request.POST.get('appointment_id')).select_related('staff', 'service', 'customer').first()
        if not appointment:
            return redirect('/verwaltung/kalender/?notice=appointment-edit-error')
        service = Service.objects.filter(pk=request.POST.get('service_id'), active=True).first()
        staff = staff_qs.filter(pk=request.POST.get('appointment_staff_id')).first()
        customer = Customer.objects.filter(pk=request.POST.get('customer_id')).first()
        starts_at = _local_dt(request.POST.get('appointment_date'), request.POST.get('appointment_time'))
        status = request.POST.get('status')
        allowed_statuses = {value for value, _ in Appointment.STATUS}
        old_day = timezone.localtime(appointment.starts_at).date()
        old_staff_id = appointment.staff_id
        if (
            not service or not staff or not customer or not starts_at or not _is_quarter(starts_at)
            or status not in allowed_statuses or not staff.services.filter(pk=service.pk).exists()
        ):
            return redirect(_calendar_url(day=old_day, view=request.POST.get('return_view') or 'day', staff_id=old_staff_id, notice='appointment-edit-error', focus_appointment=appointment.pk))

        ends_at = starts_at + timedelta(minutes=service.duration_minutes + service.buffer_minutes)
        if status in {'new', 'confirmed'}:
            conflict = Appointment.objects.filter(
                staff=staff,
                status__in=['new', 'confirmed'],
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            ).exclude(pk=appointment.pk).exists()
            blocked = BlockedPeriod.objects.filter(
                staff=staff,
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            ).exclude(reason__startswith='[NOTE]').exists()
            if conflict or blocked:
                return redirect(_calendar_url(day=old_day, view=request.POST.get('return_view') or 'day', staff_id=old_staff_id, notice='appointment-edit-error', focus_appointment=appointment.pk))

        appointment.service = service
        appointment.staff = staff
        appointment.customer = customer
        appointment.starts_at = starts_at
        appointment.ends_at = ends_at
        appointment.status = status
        try:
            appointment.full_clean()
            appointment.save(update_fields=['service', 'staff', 'customer', 'starts_at', 'ends_at', 'status', 'updated_at'])
        except ValidationError:
            return redirect(_calendar_url(day=old_day, view=request.POST.get('return_view') or 'day', staff_id=old_staff_id, notice='appointment-edit-error', focus_appointment=appointment.pk))
        return redirect(_calendar_url(day=timezone.localtime(appointment.starts_at).date(), view=request.POST.get('return_view') or 'day', staff_id=appointment.staff_id, notice='appointment-updated', focus_appointment=appointment.pk))

    if request.method == 'POST' and action == 'delete_appointment':
        appointment = Appointment.objects.filter(pk=request.POST.get('appointment_id')).first()
        if not appointment:
            return redirect('/verwaltung/buchungen/?notice=appointment-deleted')
        day = timezone.localtime(appointment.starts_at).date()
        staff_id = appointment.staff_id
        appointment.delete()
        return redirect(_calendar_url(day=day, view=request.POST.get('return_view') or 'day', staff_id=staff_id, notice='appointment-deleted'))

    if request.method == 'POST' and action == 'add_block':
        if not selected_staff:
            return redirect('/verwaltung/einstellungen/?notice=block-error')
        starts_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_start'))
        ends_at = _local_dt(request.POST.get('block_date'), request.POST.get('block_end'))
        if not starts_at or not ends_at or ends_at <= starts_at or not _is_quarter(starts_at) or not _is_quarter(ends_at):
            return redirect(f'/verwaltung/einstellungen/?staff={selected_staff.pk}&notice=block-error')
        item = BlockedPeriod.objects.create(
            staff=selected_staff,
            starts_at=starts_at,
            ends_at=ends_at,
            reason=(request.POST.get('block_reason') or 'Gesperrt').strip()[:160],
        )
        return redirect(_calendar_url(day=timezone.localtime(item.starts_at).date(), view='day', staff_id=item.staff_id, notice='block', focus_block=item.pk))

    focus_block = request.GET.get('focus_block')
    focus_appointment = request.GET.get('focus_appointment')
    if request.method == 'GET' and focus_block:
        block = BlockedPeriod.objects.filter(pk=focus_block).select_related('staff').first()
        if block:
            block_day = timezone.localtime(block.starts_at).date()
            requested_day = parse_date(request.GET.get('date') or '')
            requested_staff = request.GET.get('staff')
            if requested_day != block_day or str(requested_staff or '') != str(block.staff_id):
                return redirect(_calendar_url(day=block_day, view=request.GET.get('cal_view') or 'day', staff_id=block.staff_id, notice=request.GET.get('notice') or 'block', focus_block=block.pk))
    if request.method == 'GET' and focus_appointment:
        appointment = Appointment.objects.filter(pk=focus_appointment).first()
        if appointment:
            appointment_day = timezone.localtime(appointment.starts_at).date()
            requested_day = parse_date(request.GET.get('date') or '')
            requested_staff = request.GET.get('staff')
            if requested_day != appointment_day or str(requested_staff or '') != str(appointment.staff_id):
                return redirect(_calendar_url(day=appointment_day, view=request.GET.get('cal_view') or 'day', staff_id=appointment.staff_id, notice=request.GET.get('notice') or 'appointment-updated', focus_appointment=appointment.pk))

    response = views.dashboard(request)
    calendar_day = parse_date(request.GET.get('date') or '') or timezone.localdate()
    calendar_view = request.GET.get('cal_view') or 'day'
    return _polish_admin_response(
        response,
        selected_staff_id=selected_staff.pk if selected_staff else None,
        calendar_day=calendar_day,
        calendar_view=calendar_view,
        focus_block=focus_block,
        focus_appointment=focus_appointment,
        notice=request.GET.get('notice') or '',
    )