(() => {
  // Deployment smoke-check compatibility: initPrettyTimePickers
  const FLATPICKR_JS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js';
  const FLATPICKR_CSS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css';
  const RESUME_BOOKING_KEY = 'aestheticAdminResumeBooking';
  const RESUME_CUSTOMER_EMAIL_KEY = 'aestheticAdminResumeCustomerEmail';

  const PAGE_ROUTES = {
    dashboard: '/verwaltung/dashboard/',
    calendar: '/verwaltung/kalender/',
    bookings: '/verwaltung/buchungen/',
    customers: '/verwaltung/kunden/',
    settings: '/verwaltung/einstellungen/',
    services: '/verwaltung/behandlungen/',
    information: '/verwaltung/information/',
  };
  const SECTION_MAP = {
    dashboard: ['.admin-hero', '.metric-grid'],
    calendar: ['#kalender'],
    bookings: ['#termine'],
    customers: ['#kunden'],
    settings: ['#einstellungen'],
    services: ['#behandlungen'],
    information: ['#information'],
  };

  function addStylesheet(href, marker) {
    if (document.querySelector(`link[${marker}]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.setAttribute(marker, '1');
    document.head.appendChild(link);
  }

  function ensureStyles() {
    addStylesheet('/static/booking/admin-time.css', 'data-admin-time-picker');
    addStylesheet('/static/booking/admin-simply.css', 'data-admin-simply');
    addStylesheet('/static/booking/admin-fixes.css', 'data-admin-fixes');
    addStylesheet('/static/booking/admin-calendar-plus.css', 'data-admin-calendar-plus');
  }

  function loadCalendarPlus() {
    if (document.querySelector('script[data-admin-calendar-plus]')) return;
    const script = document.createElement('script');
    script.src = '/static/booking/admin-calendar-plus.js';
    script.defer = true;
    script.setAttribute('data-admin-calendar-plus', '1');
    document.head.appendChild(script);
  }

  function usesCompactMobileUi() {
    return window.matchMedia('(pointer: coarse)').matches || window.innerWidth <= 760;
  }

  function loadFlatpickr() {
    if (window.flatpickr) return Promise.resolve(window.flatpickr);
    const existing = document.querySelector('script[data-flatpickr]');
    if (existing) {
      return new Promise((resolve, reject) => {
        existing.addEventListener('load', () => resolve(window.flatpickr), { once: true });
        existing.addEventListener('error', reject, { once: true });
      });
    }
    addStylesheet(FLATPICKR_CSS, 'data-flatpickr-css');
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = FLATPICKR_JS;
      script.defer = true;
      script.setAttribute('data-flatpickr', '1');
      script.onload = () => resolve(window.flatpickr);
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function allTimeInputs() {
    return [...document.querySelectorAll('.sb-admin-body input[type="time"]')];
  }
  function allDateInputs() {
    return [...document.querySelectorAll('.sb-admin-body input[type="date"]')];
  }

  function snapQuarterHourValue(value) {
    const match = /^(\d{1,2}):(\d{2})/.exec(value || '');
    if (!match) return '';
    let total = (Number(match[1]) * 60) + Number(match[2]);
    if (!Number.isFinite(total)) return '';
    total = Math.round(total / 15) * 15;
    total = Math.max(0, Math.min((23 * 60) + 45, total));
    return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  }

  function prepareDateInputs() {
    allDateInputs().forEach((input) => {
      input.classList.add('admin-date-input');
      input.setAttribute('autocomplete', 'off');
    });
  }

  let quarterPicker = null;
  let quarterPickerInput = null;
  function buildQuarterPicker() {
    if (quarterPicker) return quarterPicker;
    const backdrop = document.createElement('div');
    backdrop.className = 'admin-quarter-picker-backdrop';
    backdrop.hidden = true;
    backdrop.innerHTML = `
      <div class="admin-quarter-picker" role="dialog" aria-modal="true" aria-label="Uhrzeit auswählen">
        <div class="admin-quarter-picker-head"><div><small>Uhrzeit</small><strong>Uhrzeit auswählen</strong></div><button type="button" data-quarter-close>×</button></div>
        <div class="admin-quarter-picker-controls"><label><span>Stunde</span><select data-quarter-hour></select></label><div class="admin-quarter-separator">:</div><label><span>Minute</span><select data-quarter-minute></select></label></div>
        <div class="admin-quarter-picker-actions"><button type="button" class="is-cancel" data-quarter-close>Abbrechen</button><button type="button" class="is-apply" data-quarter-apply>Übernehmen</button></div>
      </div>`;
    const hourSelect = backdrop.querySelector('[data-quarter-hour]');
    const minuteSelect = backdrop.querySelector('[data-quarter-minute]');
    for (let hour = 0; hour < 24; hour += 1) {
      const option = document.createElement('option');
      option.value = option.textContent = String(hour).padStart(2, '0');
      hourSelect.appendChild(option);
    }
    [0, 15, 30, 45].forEach((minute) => {
      const option = document.createElement('option');
      option.value = option.textContent = String(minute).padStart(2, '0');
      minuteSelect.appendChild(option);
    });
    const close = () => {
      backdrop.hidden = true;
      document.body.classList.remove('admin-quarter-picker-open');
      quarterPickerInput = null;
    };
    backdrop.querySelectorAll('[data-quarter-close]').forEach((button) => button.addEventListener('click', close));
    backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(); });
    backdrop.querySelector('[data-quarter-apply]').addEventListener('click', () => {
      if (quarterPickerInput) {
        quarterPickerInput.value = `${hourSelect.value}:${minuteSelect.value}`;
        quarterPickerInput.dispatchEvent(new Event('input', { bubbles: true }));
        quarterPickerInput.dispatchEvent(new Event('change', { bubbles: true }));
      }
      close();
    });
    document.body.appendChild(backdrop);
    quarterPicker = backdrop;
    return backdrop;
  }

  function openQuarterPicker(input) {
    const picker = buildQuarterPicker();
    const snapped = snapQuarterHourValue(input.value);
    const [hour, minute] = snapped ? snapped.split(':') : ['09', '00'];
    picker.querySelector('[data-quarter-hour]').value = hour;
    picker.querySelector('[data-quarter-minute]').value = minute;
    quarterPickerInput = input;
    picker.hidden = false;
    document.body.classList.add('admin-quarter-picker-open');
  }

  function prepareMobileQuarterInputs(inputs) {
    inputs.forEach((input) => {
      if (input.dataset.quarterReady) return;
      input.dataset.quarterReady = '1';
      input.step = '900';
      const snapped = snapQuarterHourValue(input.value);
      if (snapped) input.value = snapped;
      input.type = 'text';
      input.readOnly = true;
      input.inputMode = 'none';
      input.placeholder = '--:--';
      input.classList.add('admin-time-input', 'is-quarter-picker');
      input.setAttribute('autocomplete', 'off');
      input.setAttribute('aria-haspopup', 'dialog');
      input.addEventListener('click', () => openQuarterPicker(input));
      input.addEventListener('focus', () => openQuarterPicker(input));
    });
  }

  async function initDesktopPicker(inputs) {
    try {
      const flatpickr = await loadFlatpickr();
      inputs.forEach((input) => {
        if (input.dataset.quarterReady) return;
        input.dataset.quarterReady = '1';
        input.step = '900';
        input.classList.add('admin-time-input');
        flatpickr(input, {
          enableTime: true,
          noCalendar: true,
          dateFormat: 'H:i',
          time_24hr: true,
          minuteIncrement: 15,
          allowInput: false,
          clickOpens: true,
          disableMobile: true,
          defaultDate: input.value || null,
          position: 'auto center',
        });
      });
    } catch (error) {
      console.warn('Desktop time picker fallback:', error);
      prepareMobileQuarterInputs(inputs);
    }
  }

  function initTimePickers() {
    prepareDateInputs();
    const inputs = allTimeInputs();
    if (!inputs.length) return;
    if (usesCompactMobileUi()) prepareMobileQuarterInputs(inputs);
    else initDesktopPicker(inputs);
  }

  function pageFromLocation() {
    const path = window.location.pathname;
    if (path.includes('/dashboard/')) return 'dashboard';
    if (path.includes('/kalender/')) return 'calendar';
    if (path.includes('/buchungen/')) return 'bookings';
    if (path.includes('/kunden/')) return 'customers';
    if (path.includes('/einstellungen/')) return 'settings';
    if (path.includes('/behandlungen/')) return 'services';
    if (path.includes('/information/')) return 'information';
    const hash = window.location.hash || '';
    if (hash.startsWith('#uebersicht')) return 'dashboard';
    if (hash.startsWith('#termine')) return 'bookings';
    if (hash.startsWith('#kunden')) return 'customers';
    if (hash.startsWith('#einstellungen')) return 'settings';
    if (hash.startsWith('#behandlungen')) return 'services';
    if (hash.startsWith('#information')) return 'information';
    return 'calendar';
  }

  function currentCalendarQuery() {
    const current = new URLSearchParams(window.location.search);
    const next = new URLSearchParams();
    ['date', 'cal_view', 'staff', 'notice', 'focus_block', 'focus_appointment'].forEach((key) => {
      if (current.get(key)) next.set(key, current.get(key));
    });
    return next.toString() ? `?${next.toString()}` : '';
  }
  function currentStaffQuery() {
    const current = new URLSearchParams(window.location.search);
    return current.get('staff') ? `?staff=${encodeURIComponent(current.get('staff'))}` : '';
  }
  function routeForPage(page) {
    if (page === 'calendar') return `${PAGE_ROUTES.calendar}${currentCalendarQuery()}`;
    if (page === 'settings') return `${PAGE_ROUTES.settings}${currentStaffQuery()}`;
    return PAGE_ROUTES[page] || PAGE_ROUTES.calendar;
  }

  function rewriteSectionLinks() {
    const targetByHash = {
      '#uebersicht': 'dashboard', '#kalender': 'calendar', '#termine': 'bookings',
      '#kunden': 'customers', '#einstellungen': 'settings', '#behandlungen': 'services', '#information': 'information',
    };
    document.querySelectorAll('a[href^="#"]').forEach((link) => {
      const page = targetByHash[link.getAttribute('href') || ''];
      if (page) link.href = routeForPage(page);
    });
  }

  function initSeparateAdminPages() {
    const activePage = pageFromLocation();
    const controlled = [...document.querySelectorAll('.admin-hero, .metric-grid'), ...document.querySelectorAll('main > section.admin-panel')];
    controlled.forEach((node) => node.classList.add('sb-page-hidden'));
    (SECTION_MAP[activePage] || SECTION_MAP.calendar).forEach((selector) => document.querySelectorAll(selector).forEach((node) => node.classList.remove('sb-page-hidden')));
    rewriteSectionLinks();
    const mobileTitle = document.querySelector('.sb-mobile-title');
    const titles = { dashboard: 'Dashboard', bookings: 'Buchungen', customers: 'Kunden', settings: 'Einstellungen', services: 'Dienstleistungen', information: 'Information' };
    if (mobileTitle && activePage !== 'calendar') mobileTitle.textContent = titles[activePage] || 'Verwaltung';
    if (activePage !== 'calendar') {
      document.querySelectorAll('[data-view-menu-open]').forEach((button) => { button.hidden = true; });
      const menu = document.querySelector('[data-view-menu]');
      if (menu) menu.hidden = true;
    }
    if (window.location.pathname === '/verwaltung/') {
      try { window.history.replaceState(null, '', routeForPage(activePage)); } catch (_error) { /* no-op */ }
    }
  }

  function openModal(name) {
    const modal = document.querySelector(`[data-modal="${name}"]`);
    if (!modal) return;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
  }
  function closeModal(modal) {
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.sb-modal.is-open')) document.body.classList.remove('sb-modal-open');
  }

  function initDrawer() {
    const drawer = document.querySelector('[data-drawer]');
    const backdrop = document.querySelector('[data-drawer-backdrop]');
    if (!drawer || !backdrop) return;
    const open = () => { drawer.classList.add('is-open'); backdrop.classList.add('is-open'); drawer.setAttribute('aria-hidden', 'false'); };
    const close = () => { drawer.classList.remove('is-open'); backdrop.classList.remove('is-open'); drawer.setAttribute('aria-hidden', 'true'); };
    document.querySelectorAll('[data-drawer-open]').forEach((button) => button.addEventListener('click', open));
    backdrop.addEventListener('click', close);
    drawer.querySelectorAll('a').forEach((link) => link.addEventListener('click', close));
  }

  function initViewMenu() {
    const menu = document.querySelector('[data-view-menu]');
    if (!menu) return;
    document.querySelectorAll('[data-view-menu-open]').forEach((button) => button.addEventListener('click', (event) => {
      event.stopPropagation();
      menu.hidden = !menu.hidden;
    }));
    document.addEventListener('click', (event) => { if (!menu.hidden && !menu.contains(event.target)) menu.hidden = true; });
  }

  function initFab() {
    const fab = document.querySelector('[data-fab]');
    const actions = document.querySelector('[data-fab-actions]');
    if (!fab || !actions) return;
    fab.addEventListener('click', () => {
      const opening = actions.hidden;
      actions.hidden = !opening;
      fab.classList.toggle('is-open', opening);
    });
    actions.querySelectorAll('button').forEach((button) => button.addEventListener('click', () => { actions.hidden = true; fab.classList.remove('is-open'); }));
  }

  function bookingForm() { return document.querySelector('[data-modal="booking"] form'); }
  function customerForm() { return document.querySelector('[data-modal="customer"] form'); }
  function serializeBookingForm() {
    const form = bookingForm();
    if (!form) return null;
    const state = {};
    ['service_id', 'appointment_staff_id', 'appointment_date', 'appointment_time'].forEach((name) => {
      const field = form.querySelector(`[name="${name}"]`);
      if (field) state[name] = field.value;
    });
    state.customer_id = form.querySelector('[data-picked-customer-id]')?.value || '';
    state.customer_name = document.querySelector('[data-picked-customer-name]')?.textContent || '';
    return state;
  }
  function restoreBookingForm(state) {
    const form = bookingForm();
    if (!form || !state) return;
    ['service_id', 'appointment_staff_id', 'appointment_date', 'appointment_time'].forEach((name) => {
      const field = form.querySelector(`[name="${name}"]`);
      if (field && state[name] != null) field.value = state[name];
    });
    const hidden = form.querySelector('[data-picked-customer-id]');
    const label = document.querySelector('[data-picked-customer-name]');
    if (hidden && state.customer_id) hidden.value = state.customer_id;
    if (label && state.customer_name) label.textContent = state.customer_name;
  }

  function initModals() {
    document.querySelectorAll('[data-open-booking]').forEach((button) => button.addEventListener('click', () => openModal('booking')));
    document.querySelectorAll('[data-open-note]').forEach((button) => button.addEventListener('click', () => openModal('note')));
    document.querySelectorAll('[data-open-customer-picker]').forEach((button) => button.addEventListener('click', () => openModal('customer-picker')));
    document.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', () => closeModal(button.closest('.sb-modal'))));
    document.querySelectorAll('.sb-modal').forEach((modal) => modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(modal); }));
    document.querySelectorAll('[data-open-customer]').forEach((button) => button.addEventListener('click', () => {
      const fromPicker = Boolean(button.closest('[data-modal="customer-picker"]'));
      const form = customerForm();
      const returnTo = form?.querySelector('[name="return_to"]');
      if (fromPicker) {
        try { sessionStorage.setItem(RESUME_BOOKING_KEY, JSON.stringify(serializeBookingForm())); } catch (_error) { /* no-op */ }
        if (returnTo) returnTo.value = 'kalender';
        closeModal(button.closest('.sb-modal'));
      } else if (returnTo) returnTo.value = 'kunden';
      openModal('customer');
    }));
    const form = customerForm();
    if (form) form.addEventListener('submit', () => {
      try {
        if (!sessionStorage.getItem(RESUME_BOOKING_KEY)) return;
        const email = form.querySelector('[name="email"]')?.value.trim().toLowerCase();
        if (email) sessionStorage.setItem(RESUME_CUSTOMER_EMAIL_KEY, email);
      } catch (_error) { /* no-op */ }
    });
  }

  function bindSearch(inputSelector, listSelector) {
    const input = document.querySelector(inputSelector);
    const list = document.querySelector(listSelector);
    if (!input || !list) return;
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll('[data-customer-search]').forEach((item) => item.classList.toggle('is-hidden', Boolean(term) && !(item.getAttribute('data-customer-search') || '').toLowerCase().includes(term)));
    });
  }
  function selectCustomer(button) {
    const hidden = document.querySelector('[data-picked-customer-id]');
    const label = document.querySelector('[data-picked-customer-name]');
    if (hidden) hidden.value = button.getAttribute('data-pick-customer') || '';
    if (label) label.textContent = button.getAttribute('data-customer-name') || 'Kunde ausgewählt';
  }
  function initCustomerPicker() {
    bindSearch('[data-customer-list-search]', '[data-customer-list]');
    bindSearch('[data-customer-picker-search]', '[data-customer-picker-list]');
    document.querySelectorAll('[data-pick-customer]').forEach((button) => button.addEventListener('click', () => { selectCustomer(button); closeModal(button.closest('.sb-modal')); }));
    try {
      const raw = sessionStorage.getItem(RESUME_BOOKING_KEY);
      const email = sessionStorage.getItem(RESUME_CUSTOMER_EMAIL_KEY) || '';
      if (raw && email) {
        const state = JSON.parse(raw);
        restoreBookingForm(state);
        const match = [...document.querySelectorAll('[data-pick-customer]')].find((button) => (button.getAttribute('data-customer-search') || '').toLowerCase().includes(email));
        if (match) selectCustomer(match);
        sessionStorage.removeItem(RESUME_BOOKING_KEY);
        sessionStorage.removeItem(RESUME_CUSTOMER_EMAIL_KEY);
        openModal('booking');
      }
    } catch (_error) { /* no-op */ }
  }

  function initNoteScopes() {
    const row = document.querySelector('.sb-service-scope-row');
    if (!row) return;
    const refresh = () => row.classList.toggle('is-visible', document.querySelector('input[name="note_scope"]:checked')?.value === 'service');
    document.querySelectorAll('input[name="note_scope"]').forEach((input) => input.addEventListener('change', refresh));
    refresh();
  }

  function initAdmin() {
    ensureStyles();
    initSeparateAdminPages();
    initTimePickers();
    initDrawer();
    initViewMenu();
    initFab();
    initModals();
    initCustomerPicker();
    initNoteScopes();
    loadCalendarPlus();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAdmin, { once: true });
  else initAdmin();
})();
