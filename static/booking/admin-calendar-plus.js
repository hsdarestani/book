(() => {
  const AVAILABILITY_API = '/verwaltung/api/day-availability/';
  const CALENDAR_DAY_API = '/verwaltung/api/calendar-day/';
  const CAL_START = 8 * 60;
  const CAL_END = 20 * 60;
  const CAL_TOTAL = CAL_END - CAL_START;
  const dayCache = new Map();
  const pendingDays = new Map();

  function onCalendarPage() {
    return window.location.pathname.includes('/verwaltung/kalender/') || window.location.pathname === '/verwaltung/';
  }

  function currentCalendarView() {
    return new URLSearchParams(window.location.search).get('cal_view') || 'day';
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

  function currentCalendarDate() {
    return calendarDates()[0] || isoDate(new Date());
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

  let availabilityModal = null;
  let activeData = null;

  function buildAvailabilityModal() {
    if (availabilityModal) return availabilityModal;
    availabilityModal = document.createElement('div');
    availabilityModal.className = 'sb-modal sb-day-availability-modal';
    availabilityModal.setAttribute('aria-hidden', 'true');
    availabilityModal.innerHTML = `
      <div class="sb-modal-card sb-form-sheet">
        <div class="sb-sheet-head"><button type="button" data-day-close>×</button><strong>Tages-Verfügbarkeit</strong><span></span></div>
        <div class="sb-sheet-section-title" data-day-title>Arbeitszeit für diesen Tag</div>
        <form method="post" action="${AVAILABILITY_API}" class="sb-sheet-form sb-day-availability-form">
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
    document.body.appendChild(availabilityModal);
    availabilityModal.querySelectorAll('[data-day-close]').forEach((button) => button.addEventListener('click', closeAvailabilityModal));
    availabilityModal.addEventListener('click', (event) => { if (event.target === availabilityModal) closeAvailabilityModal(); });
    availabilityModal.querySelector('[name="closed"]').addEventListener('change', syncClosedState);
    return availabilityModal;
  }

  function closeAvailabilityModal() {
    if (!availabilityModal) return;
    availabilityModal.classList.remove('is-open');
    availabilityModal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('sb-modal-open');
  }

  function syncClosedState() {
    if (!availabilityModal) return;
    const closed = availabilityModal.querySelector('[name="closed"]').checked;
    availabilityModal.querySelector('.sb-day-ranges').classList.toggle('is-disabled', closed);
    availabilityModal.querySelectorAll('.sb-day-ranges select').forEach((select) => { select.disabled = closed; });
  }

  function formatGermanDate(value) {
    const date = parseIsoDate(value);
    return date ? new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(date) : value;
  }

  function openAvailabilityEditor(data) {
    activeData = data;
    const node = buildAvailabilityModal();
    const form = node.querySelector('form');
    form.elements.csrfmiddlewaretoken.value = csrfToken();
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
    const response = await fetch(`${AVAILABILITY_API}?staff=${encodeURIComponent(staffId)}&date=${encodeURIComponent(date)}`, {
      credentials: 'same-origin',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`Availability HTTP ${response.status}`);
    return response.json();
  }

  function dayCacheKey(staffId, date) {
    return `${staffId}:${date}`;
  }

  function loadCalendarDay(staffId, date) {
    const key = dayCacheKey(staffId, date);
    if (dayCache.has(key)) return Promise.resolve(dayCache.get(key));
    if (pendingDays.has(key)) return pendingDays.get(key);

    const request = fetch(`${CALENDAR_DAY_API}?staff=${encodeURIComponent(staffId)}&date=${encodeURIComponent(date)}`, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Calendar HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        if (!data.ok) throw new Error(data.error || 'Calendar payload invalid');
        dayCache.set(key, data);
        return data;
      })
      .finally(() => pendingDays.delete(key));

    pendingDays.set(key, request);
    return request;
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
      const label = document.createElement('span');
      label.textContent = `${range.start}–${range.end}`;
      const edit = document.createElement('b');
      edit.textContent = '✎';
      segment.append(label, edit);
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

  function showExistingModal(name) {
    const node = document.querySelector(`[data-modal="${name}"]`);
    if (!node) return null;
    node.classList.add('is-open');
    node.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
    return node;
  }

  function openDynamicAppointment(data) {
    const modal = showExistingModal('appointment-edit');
    const form = modal?.querySelector('[data-appointment-edit-form]');
    if (!form) return;
    form.elements.appointment_id.value = data.id;
    form.elements.service_id.value = data.service_id;
    form.elements.appointment_staff_id.value = data.staff_id;
    form.elements.customer_id.value = data.customer_id;
    form.elements.appointment_date.value = data.date;
    form.elements.appointment_time.value = data.time;
    form.elements.status.value = data.status;
  }

  function openDynamicBlock(data) {
    const modal = showExistingModal('calendar-item-edit');
    const form = modal?.querySelector('[data-calendar-item-edit-form]');
    if (!form) return;
    form.elements.block_id.value = data.id;
    form.elements.staff_id.value = data.staff_id;
    form.elements.item_kind.value = data.kind;
    form.elements.item_date.value = data.date;
    form.elements.item_start.value = data.start;
    form.elements.item_end.value = data.end;
    form.elements.item_text.value = data.text || '';
    form.elements.item_service_id.value = data.service_id || '';
    form.querySelectorAll('input[name="item_scope"]').forEach((radio) => { radio.checked = radio.value === data.scope; });
    form.querySelector('.sb-edit-service-row')?.classList.toggle('is-visible', data.scope === 'service');
    const title = modal.querySelector('[data-edit-block-title]');
    if (title) title.textContent = data.kind === 'note' ? 'Notiz bearbeiten' : 'Sperrzeit bearbeiten';
  }

  function createAppointmentNode(data) {
    const node = document.createElement('a');
    node.className = 'sb-calendar-event';
    node.href = '#termine';
    node.style.top = `${data.top}%`;
    node.style.height = `${data.height}%`;
    node.dataset.fastAppointmentId = String(data.id);
    node.title = `${data.customer_name} – ${data.service_name}`;

    const customer = document.createElement('strong');
    customer.textContent = data.customer_name;
    const service = document.createElement('span');
    service.textContent = data.service_name;
    const time = document.createElement('small');
    time.textContent = `${data.start}–${data.end}`;
    node.append(customer, service, time);
    node.addEventListener('click', (event) => {
      event.preventDefault();
      openDynamicAppointment(data);
    });
    return node;
  }

  function createBlockNode(data) {
    const node = document.createElement('div');
    node.className = `sb-calendar-block is-${data.visual_kind || (data.kind === 'note' ? 'note' : 'blocked')}`;
    node.style.top = `${data.top}%`;
    node.style.height = `${data.height}%`;
    node.dataset.fastBlockId = String(data.id);
    node.tabIndex = 0;
    node.setAttribute('role', 'button');

    const label = document.createElement('strong');
    label.textContent = data.text || (data.kind === 'note' ? 'Notiz' : 'Gesperrt');
    const time = document.createElement('small');
    time.textContent = `${data.start}–${data.end}`;
    const menu = document.createElement('button');
    menu.type = 'button';
    menu.className = 'sb-event-menu';
    menu.textContent = '⋮';
    menu.setAttribute('aria-label', 'Eintrag bearbeiten');
    menu.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      openDynamicBlock(data);
    });
    node.append(label, time, menu);
    node.addEventListener('click', () => openDynamicBlock(data));
    node.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openDynamicBlock(data);
      }
    });
    return node;
  }

  function dateLabels(dateValue) {
    const date = parseIsoDate(dateValue);
    if (!date) return null;
    return {
      title: new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(date),
      month: new Intl.DateTimeFormat('de-DE', { month: 'long', year: 'numeric' }).format(date),
      weekday: new Intl.DateTimeFormat('de-DE', { weekday: 'long' }).format(date),
      shortDate: new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit' }).format(date),
    };
  }

  function navHref(dateValue) {
    const params = new URLSearchParams(window.location.search);
    params.set('date', dateValue);
    params.set('cal_view', 'day');
    const staffId = selectedStaff();
    if (staffId) params.set('staff', staffId);
    params.delete('notice');
    params.delete('focus_block');
    params.delete('focus_appointment');
    return `${window.location.pathname}?${params.toString()}#kalender`;
  }

  function syncDateControls(dateValue) {
    document.querySelectorAll('input[name="return_date"]').forEach((input) => { input.value = dateValue; });
    document.querySelectorAll('input[name="return_view"]').forEach((input) => { input.value = 'day'; });
    ['note_date', 'block_date', 'appointment_date'].forEach((name) => {
      document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
        if (!input.closest('[data-modal="appointment-edit"]') && !input.closest('[data-modal="calendar-item-edit"]')) {
          input.value = dateValue;
        }
      });
    });
  }

  function updateDateNavigation(dateValue) {
    const date = parseIsoDate(dateValue);
    if (!date) return;
    const arrows = document.querySelectorAll('.sb-date-nav .sb-date-arrow');
    if (arrows[0]) arrows[0].href = navHref(isoDate(addDays(date, -1)));
    if (arrows[1]) arrows[1].href = navHref(isoDate(addDays(date, 1)));
  }

  function renderCalendarDay(data, { updateHistory = true } = {}) {
    const dayNode = document.querySelector('.sb-calendar-days .sb-calendar-day');
    const track = dayNode?.querySelector('.sb-day-track');
    if (!dayNode || !track) return;

    const labels = dateLabels(data.date);
    const title = document.querySelector('.sb-date-title');
    if (labels && title) {
      const strong = title.querySelector('strong');
      const span = title.querySelector('span');
      if (strong) strong.textContent = labels.title;
      if (span) span.textContent = labels.month;
    }

    const head = dayNode.querySelector('.sb-day-head');
    if (labels && head) {
      head.replaceChildren();
      const weekday = document.createElement('span');
      weekday.textContent = labels.weekday;
      const date = document.createElement('b');
      date.textContent = labels.shortDate;
      head.append(weekday, date);
    }

    dayNode.classList.toggle('is-today', Boolean(data.is_today));
    track.replaceChildren();
    (data.appointments || []).forEach((item) => track.appendChild(createAppointmentNode(item)));
    (data.blocks || []).forEach((item) => track.appendChild(createBlockNode(item)));
    renderWorkingSegments(dayNode, data);
    syncDateControls(data.date);
    updateDateNavigation(data.date);
    layoutAppointments();

    if (updateHistory) {
      const params = new URLSearchParams(window.location.search);
      params.set('date', data.date);
      params.set('cal_view', 'day');
      params.set('staff', String(data.staff_id));
      params.delete('notice');
      params.delete('focus_block');
      params.delete('focus_appointment');
      window.history.pushState({ calendarDate: data.date }, '', `${window.location.pathname}?${params.toString()}#kalender`);
    }

    document.querySelector('.sb-calendar-panel')?.setAttribute('aria-busy', 'false');
    prefetchNeighbors(String(data.staff_id), data.date);
  }

  function prefetchNeighbors(staffId, dateValue) {
    const date = parseIsoDate(dateValue);
    if (!staffId || !date) return;
    [isoDate(addDays(date, -1)), isoDate(addDays(date, 1))].forEach((neighbor) => {
      loadCalendarDay(staffId, neighbor).catch(() => {});
    });
  }

  async function navigateToDay(dateValue, { updateHistory = true } = {}) {
    if (currentCalendarView() !== 'day') return false;
    const staffId = selectedStaff();
    if (!staffId || !parseIsoDate(dateValue)) return false;
    const panel = document.querySelector('.sb-calendar-panel');
    panel?.setAttribute('aria-busy', 'true');
    try {
      const data = await loadCalendarDay(staffId, dateValue);
      renderCalendarDay(data, { updateHistory });
      return true;
    } catch (error) {
      console.warn('Fast calendar navigation failed:', error);
      panel?.setAttribute('aria-busy', 'false');
      return false;
    }
  }

  function installFastDayNavigation() {
    if (currentCalendarView() !== 'day') return;
    document.addEventListener('click', async (event) => {
      const arrow = event.target.closest('.sb-date-nav .sb-date-arrow');
      if (!arrow) return;
      let targetDate = '';
      try {
        targetDate = new URL(arrow.href, window.location.origin).searchParams.get('date') || '';
      } catch (_error) {
        return;
      }
      if (!targetDate) return;
      event.preventDefault();
      const success = await navigateToDay(targetDate);
      if (!success) window.location.assign(arrow.href);
    });

    window.addEventListener('popstate', () => {
      const dateValue = new URLSearchParams(window.location.search).get('date');
      if (dateValue) navigateToDay(dateValue, { updateHistory: false });
    });
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
    installFastDayNavigation();

    const staffId = selectedStaff();
    if (currentCalendarView() === 'day' && staffId) {
      prefetchNeighbors(staffId, currentCalendarDate());
    }

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
