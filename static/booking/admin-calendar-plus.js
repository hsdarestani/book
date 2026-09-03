(() => {
  const API = '/verwaltung/api/day-availability/';
  const CAL_START = 8 * 60;
  const CAL_END = 20 * 60;
  const CAL_TOTAL = CAL_END - CAL_START;

  function onCalendarPage() {
    return window.location.pathname.includes('/verwaltung/kalender/') || window.location.pathname === '/verwaltung/';
  }

  function parseIsoDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12, 0, 0, 0);
  }

  function isoDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }

  function addDays(date, amount) {
    const next = new Date(date.getTime());
    next.setDate(next.getDate() + amount);
    return next;
  }

  function calendarDates() {
    const params = new URLSearchParams(window.location.search);
    const selected = parseIsoDate(params.get('date')) || new Date();
    const isWeek = (params.get('cal_view') || 'day') === 'week';
    if (!isWeek) return [isoDate(selected)];
    const mondayOffset = (selected.getDay() + 6) % 7;
    const monday = addDays(selected, -mondayOffset);
    return Array.from({ length: 7 }, (_, index) => isoDate(addDays(monday, index)));
  }

  function selectedStaff() {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get('staff');
    if (fromQuery) return fromQuery;
    const active = document.querySelector('.sb-provider-switcher .doctor-pill.is-active');
    if (!active) return '';
    try {
      const url = new URL(active.href, window.location.origin);
      return url.searchParams.get('staff') || '';
    } catch (_error) {
      return '';
    }
  }

  function minutes(value) {
    const match = /^(\d{1,2}):(\d{2})$/.exec(value || '');
    if (!match) return null;
    return (Number(match[1]) * 60) + Number(match[2]);
  }

  function positionFor(start, end) {
    const startMinute = Math.max(CAL_START, minutes(start) ?? CAL_START);
    const endMinute = Math.min(CAL_END, minutes(end) ?? CAL_END);
    return {
      top: Math.max(0, ((startMinute - CAL_START) / CAL_TOTAL) * 100),
      height: Math.max(0, ((Math.max(endMinute, startMinute) - startMinute) / CAL_TOTAL) * 100),
    };
  }

  function csrfToken() {
    return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value || '';
  }

  function timeOptions(selected = '') {
    const out = [];
    for (let hour = 0; hour < 24; hour += 1) {
      for (const minute of [0, 15, 30, 45]) {
        const value = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
        out.push(`<option value="${value}"${value === selected ? ' selected' : ''}>${value}</option>`);
      }
    }
    return out.join('');
  }

  let modal = null;
  let activeData = null;

  function buildModal() {
    if (modal) return modal;
    modal = document.createElement('div');
    modal.className = 'sb-modal sb-day-availability-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML = `
      <div class="sb-modal-card sb-form-sheet">
        <div class="sb-sheet-head"><button type="button" data-day-close>×</button><strong>Tages-Verfügbarkeit</strong><span></span></div>
        <div class="sb-sheet-section-title" data-day-title>Arbeitszeit für diesen Tag</div>
        <form method="post" action="${API}" class="sb-sheet-form sb-day-availability-form">
          <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken()}">
          <input type="hidden" name="staff_id">
          <input type="hidden" name="date">
          <label class="sb-block-toggle sb-day-closed-toggle">
            <div><strong>Ganztägig nicht verfügbar</strong><span>Für diesen Tag werden keine Online-Termine angeboten.</span></div>
            <input type="checkbox" name="closed"><i></i>
          </label>
          <div class="sb-day-ranges">
            <div class="sb-day-range">
              <small>Zeitraum 1</small>
              <div><select name="start_1"></select><span>bis</span><select name="end_1"></select></div>
            </div>
            <div class="sb-day-range">
              <small>Zeitraum 2 <em>optional</em></small>
              <div><select name="start_2"><option value="">—</option></select><span>bis</span><select name="end_2"><option value="">—</option></select></div>
            </div>
          </div>
          <div class="sb-day-source-note" data-day-source></div>
          <div class="sb-edit-actions">
            <button type="submit" name="action" value="save" class="sb-sheet-save">Für diesen Tag speichern</button>
            <button type="submit" name="action" value="reset" formnovalidate class="sb-day-reset">Auf Wochenplan zurücksetzen</button>
          </div>
        </form>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-day-close]').forEach((button) => button.addEventListener('click', closeModal));
    modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(); });
    modal.querySelector('[name="closed"]').addEventListener('change', syncClosedState);
    return modal;
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sb-modal-open');
  }

  function syncClosedState() {
    if (!modal) return;
    const closed = modal.querySelector('[name="closed"]').checked;
    modal.querySelector('.sb-day-ranges').classList.toggle('is-disabled', closed);
    modal.querySelectorAll('.sb-day-ranges select').forEach((select) => { select.disabled = closed; });
  }

  function formatGermanDate(value) {
    const date = parseIsoDate(value);
    return date ? new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(date) : value;
  }

  function openAvailabilityEditor(data) {
    activeData = data;
    const node = buildModal();
    const form = node.querySelector('form');
    form.elements.staff_id.value = data.staff_id;
    form.elements.date.value = data.date;
    form.elements.closed.checked = Boolean(data.closed);

    const first = data.ranges?.[0] || { start: '10:00', end: '18:00' };
    const second = data.ranges?.[1] || { start: '', end: '' };
    form.elements.start_1.innerHTML = timeOptions(first.start);
    form.elements.end_1.innerHTML = timeOptions(first.end);
    form.elements.start_2.innerHTML = `<option value="">—</option>${timeOptions(second.start)}`;
    form.elements.end_2.innerHTML = `<option value="">—</option>${timeOptions(second.end)}`;
    form.elements.start_1.value = first.start || '10:00';
    form.elements.end_1.value = first.end || '18:00';
    form.elements.start_2.value = second.start || '';
    form.elements.end_2.value = second.end || '';

    node.querySelector('[data-day-title]').textContent = `Arbeitszeit · ${formatGermanDate(data.date)}`;
    node.querySelector('[data-day-source]').textContent = data.is_override
      ? 'Für diesen Tag gilt bereits eine individuelle Arbeitszeit.'
      : 'Aktuell wird der normale Wochenplan verwendet.';
    node.querySelector('.sb-day-reset').hidden = !data.is_override;
    syncClosedState();
    node.classList.add('is-open');
    node.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
  }

  async function loadAvailability(staffId, date) {
    const response = await fetch(`${API}?staff=${encodeURIComponent(staffId)}&date=${encodeURIComponent(date)}`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`Availability HTTP ${response.status}`);
    return response.json();
  }

  function renderWorkingSegments(dayNode, data) {
    const track = dayNode.querySelector('.sb-day-track');
    if (!track) return;
    track.querySelectorAll('.sb-working-segment').forEach((node) => node.remove());

    (data.ranges || []).forEach((range) => {
      const pos = positionFor(range.start, range.end);
      if (pos.height <= 0) return;
      const segment = document.createElement('button');
      segment.type = 'button';
      segment.className = `sb-working-segment sb-working-segment-editable${data.is_override ? ' is-day-override' : ''}`;
      segment.style.top = `${pos.top}%`;
      segment.style.height = `${pos.height}%`;
      segment.innerHTML = `<span>${range.start}–${range.end}</span><b>✎</b>`;
      segment.setAttribute('aria-label', `Arbeitszeit ${range.start} bis ${range.end} bearbeiten`);
      segment.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        openAvailabilityEditor(data);
      });
      track.prepend(segment);
    });

    const head = dayNode.querySelector('.sb-day-head');
    if (head && !head.querySelector('.sb-day-hours-edit')) {
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'sb-day-hours-edit';
      edit.textContent = '✎';
      edit.setAttribute('aria-label', 'Tages-Verfügbarkeit bearbeiten');
      edit.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        openAvailabilityEditor(data);
      });
      head.appendChild(edit);
    }
    dayNode.classList.toggle('is-day-closed', Boolean(data.closed));
  }

  function positionTimeAxis() {
    if (window.innerWidth > 760) return;
    const axis = document.querySelector('.sb-time-axis');
    if (!axis) return;
    [...axis.querySelectorAll('span')].forEach((label, index) => {
      label.style.top = `${45 + (index * 120)}px`;
    });
  }

  function layoutAppointments() {
    document.querySelectorAll('.sb-day-track').forEach((track) => {
      const events = [...track.querySelectorAll('.sb-calendar-event')].map((node) => {
        const top = Number.parseFloat(node.style.top) || 0;
        const height = Number.parseFloat(node.style.height) || 0;
        node.style.left = '';
        node.style.right = '';
        node.style.width = '';
        return { node, top, bottom: top + height, col: 0 };
      }).sort((a, b) => a.top - b.top || a.bottom - b.bottom);

      let cluster = [];
      let clusterEnd = -1;
      const flush = () => {
        if (!cluster.length) return;
        const colEnds = [];
        cluster.forEach((event) => {
          let col = colEnds.findIndex((end) => end <= event.top + 0.0001);
          if (col < 0) col = colEnds.length;
          event.col = col;
          colEnds[col] = event.bottom;
        });
        const cols = Math.max(1, colEnds.length);
        cluster.forEach((event) => {
          const gap = 2;
          const width = 100 / cols;
          event.node.style.left = `calc(${event.col * width}% + ${gap}px)`;
          event.node.style.right = 'auto';
          event.node.style.width = `calc(${width}% - ${gap * 2}px)`;
          event.node.classList.toggle('is-overlap-layout', cols > 1);
        });
        cluster = [];
        clusterEnd = -1;
      };

      events.forEach((event) => {
        if (cluster.length && event.top >= clusterEnd - 0.0001) flush();
        cluster.push(event);
        clusterEnd = Math.max(clusterEnd, event.bottom);
      });
      flush();
    });
  }

  async function initEditableAvailability() {
    if (!onCalendarPage()) return;
    const staffId = selectedStaff();
    const days = [...document.querySelectorAll('.sb-calendar-day')];
    if (!staffId || !days.length) return;
    const dates = calendarDates();

    await Promise.all(days.map(async (dayNode, index) => {
      const date = dates[index];
      if (!date) return;
      try {
        const data = await loadAvailability(staffId, date);
        if (data.ok) renderWorkingSegments(dayNode, data);
      } catch (error) {
        console.warn('Daily availability could not be loaded:', error);
      }
    }));
  }

  async function init() {
    if (!onCalendarPage()) return;
    document.body.classList.add('sb-calendar-pro');
    positionTimeAxis();
    layoutAppointments();
    await initEditableAvailability();
    layoutAppointments();
    window.addEventListener('resize', () => {
      positionTimeAxis();
      layoutAppointments();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
