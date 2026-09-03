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
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (!Number.isFinite(hour) || !Number.isFinite(minute)) return '';
    let total = (hour * 60) + minute;
    total = Math.round(total / 15) * 15;
    total = Math.max(0, Math.min((23 * 60) + 45, total));
    const nextHour = Math.floor(total / 60);
    const nextMinute = total % 60;
    return `${String(nextHour).padStart(2, '0')}:${String(nextMinute).padStart(2, '0')}`;
  }

  function snapQuarterHour(input) {
    if (!input || !input.value) return;
    const snapped = snapQuarterHourValue(input.value);
    if (snapped) input.value = snapped;
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
        <div class="admin-quarter-picker-head">
          <div><small>Uhrzeit</small><strong>Uhrzeit auswählen</strong></div>
          <button type="button" data-quarter-close aria-label="Schließen">×</button>
        </div>
        <div class="admin-quarter-picker-controls">
          <label><span>Stunde</span><select data-quarter-hour></select></label>
          <div class="admin-quarter-separator">:</div>
          <label><span>Minute</span><select data-quarter-minute></select></label>
        </div>
        <div class="admin-quarter-picker-actions">
          <button type="button" class="is-cancel" data-quarter-close>Abbrechen</button>
          <button type="button" class="is-apply" data-quarter-apply>Übernehmen</button>
        </div>
      </div>`;

    const hourSelect = backdrop.querySelector('[data-quarter-hour]');
    const minuteSelect = backdrop.querySelector('[data-quarter-minute]');
    for (let hour = 0; hour < 24; hour += 1) {
      const option = document.createElement('option');
      option.value = String(hour).padStart(2, '0');
      option.textContent = option.value;
      hourSelect.appendChild(option);
    }
    [0, 15, 30, 45].forEach((minute) => {
      const option = document.createElement('option');
      option.value = String(minute).padStart(2, '0');
      option.textContent = option.value;
      minuteSelect.appendChild(option);
    });

    const close = () => {
      backdrop.hidden = true;
      document.body.classList.remove('admin-quarter-picker-open');
      quarterPickerInput = null;
    };

    backdrop.querySelectorAll('[data-quarter-close]').forEach((button) => button.addEventListener('click', close));
    backdrop.addEventListener('click', (event) => {
      if (event.target === backdrop) close();
    });
    backdrop.querySelector('[data-quarter-apply]').addEventListener('click', () => {
      if (!quarterPickerInput) return close();
      quarterPickerInput.value = `${hourSelect.value}:${minuteSelect.value}`;
      quarterPickerInput.dispatchEvent(new Event('input', { bubbles: true }));
      quarterPickerInput.dispatchEvent(new Event('change', { bubbles: true }));
      close();
    });

    document.body.appendChild(backdrop);
    quarterPicker = backdrop;
    return backdrop;
  }

  function openQuarterPicker(input) {
    const picker = buildQuarterPicker();
    const hourSelect = picker.querySelector('[data-quarter-hour]');
    const minuteSelect = picker.querySelector('[data-quarter-minute]');
    const snapped = snapQuarterHourValue(input.value);
    let hour = '09';
    let minute = '00';
    if (snapped) [hour, minute] = snapped.split(':');
    hourSelect.value = hour;
    minuteSelect.value = minute;
    quarterPickerInput = input;
    picker.hidden = false;
    document.body.classList.add('admin-quarter-picker-open');
  }

  function prepareMobileQuarterInputs(inputs) {
    inputs.forEach((input) => {
      input.step = '900';
      snapQuarterHour(input);
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
      if (!flatpickr) throw new Error('Flatpickr unavailable');
      inputs.forEach((input) => {
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
          onReady: (_selectedDates, _dateStr, instance) => {
            instance.input.classList.add('is-flatpickr');
            instance.input.setAttribute('autocomplete', 'off');
          },
          onChange: (_selectedDates, _dateStr, instance) => snapQuarterHour(instance.input),
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
    if (usesCompactMobileUi()) {
      prepareMobileQuarterInputs(inputs);
      return;
    }
    initDesktopPicker(inputs);
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
    ['date', 'cal_view', 'staff', 'notice'].forEach((key) => {
      if (current.get(key)) next.set(key, current.get(key));
    });
    const query = next.toString();
    return query ? `?${query}` : '';
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
      '#uebersicht': 'dashboard',
      '#kalender': 'calendar',
      '#termine': 'bookings',
      '#kunden': 'customers',
      '#einstellungen': 'settings',
      '#behandlungen': 'services',
      '#information': 'information',
    };
    document.querySelectorAll('a[href^="#"]').forEach((link) => {
      const href = link.getAttribute('href') || '';
      const page = targetByHash[href];
      if (page) link.href = routeForPage(page);
    });
  }

  function initSeparateAdminPages() {
    const activePage = pageFromLocation();
    const controlled = [
      ...document.querySelectorAll('.admin-hero, .metric-grid'),
      ...document.querySelectorAll('main > section.admin-panel'),
    ];
    controlled.forEach((node) => node.classList.add('sb-page-hidden'));
    (SECTION_MAP[activePage] || SECTION_MAP.calendar).forEach((selector) => {
      document.querySelectorAll(selector).forEach((node) => node.classList.remove('sb-page-hidden'));
    });

    rewriteSectionLinks();

    const mobileTitle = document.querySelector('.sb-mobile-title');
    const titleMap = {
      dashboard: 'Dashboard',
      bookings: 'Buchungen',
      customers: 'Kunden',
      settings: 'Einstellungen',
      services: 'Dienstleistungen',
      information: 'Information',
    };
    if (mobileTitle && activePage !== 'calendar') mobileTitle.textContent = titleMap[activePage] || 'Verwaltung';

    if (activePage !== 'calendar') {
      document.querySelectorAll('[data-view-menu-open]').forEach((button) => { button.hidden = true; });
      const menu = document.querySelector('[data-view-menu]');
      if (menu) menu.hidden = true;
    }

    if (window.location.pathname === '/verwaltung/') {
      const cleanRoute = routeForPage(activePage);
      try { window.history.replaceState(null, '', cleanRoute); } catch (_error) { /* no-op */ }
    }
  }

  function openModal(name) {
    const modal = document.querySelector(`[data-modal="${name}"]`);
    if (!modal) return;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('sb-modal-open');
    const autofocus = modal.querySelector('input[autofocus], input[type="search"]');
    if (autofocus) setTimeout(() => autofocus.focus(), 50);
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
    const open = () => {
      drawer.classList.add('is-open');
      backdrop.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false');
    };
    const close = () => {
      drawer.classList.remove('is-open');
      backdrop.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
    };
    document.querySelectorAll('[data-drawer-open]').forEach((button) => button.addEventListener('click', open));
    backdrop.addEventListener('click', close);
    drawer.querySelectorAll('a').forEach((link) => link.addEventListener('click', close));
  }

  function initViewMenu() {
    const menu = document.querySelector('[data-view-menu]');
    if (!menu) return;
    const toggle = () => { menu.hidden = !menu.hidden; };
    document.querySelectorAll('[data-view-menu-open]').forEach((button) => button.addEventListener('click', (event) => {
      event.stopPropagation();
      toggle();
    }));
    menu.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => { menu.hidden = true; }));
    document.addEventListener('click', (event) => {
      if (!menu.hidden && !menu.contains(event.target)) menu.hidden = true;
    });
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
    actions.querySelectorAll('button').forEach((button) => button.addEventListener('click', () => {
      actions.hidden = true;
      fab.classList.remove('is-open');
    }));
  }

  function bookingForm() {
    return document.querySelector('[data-modal="booking"] form');
  }

  function customerForm() {
    return document.querySelector('[data-modal="customer"] form');
  }

  function serializeBookingForm() {
    const form = bookingForm();
    if (!form) return null;
    const names = ['service_id', 'appointment_staff_id', 'appointment_date', 'appointment_time'];
    const state = {};
    names.forEach((name) => {
      const field = form.querySelector(`[name="${name}"]`);
      if (field) state[name] = field.value;
    });
    const customerId = form.querySelector('[data-picked-customer-id]');
    const customerName = document.querySelector('[data-picked-customer-name]');
    state.customer_id = customerId ? customerId.value : '';
    state.customer_name = customerName ? customerName.textContent : '';
    return state;
  }

  function restoreBookingForm(state) {
    const form = bookingForm();
    if (!form || !state) return;
    ['service_id', 'appointment_staff_id', 'appointment_date', 'appointment_time'].forEach((name) => {
      const field = form.querySelector(`[name="${name}"]`);
      if (field && state[name] != null) field.value = state[name];
    });
    const customerId = form.querySelector('[data-picked-customer-id]');
    const customerName = document.querySelector('[data-picked-customer-name]');
    if (customerId && state.customer_id) customerId.value = state.customer_id;
    if (customerName && state.customer_name) customerName.textContent = state.customer_name;
  }

  function rememberBookingForNewCustomer() {
    try {
      const state = serializeBookingForm();
      if (state) sessionStorage.setItem(RESUME_BOOKING_KEY, JSON.stringify(state));
    } catch (_error) {
      // sessionStorage can be unavailable in strict/private browser modes.
    }
  }

  function initModals() {
    document.querySelectorAll('[data-open-booking]').forEach((button) => button.addEventListener('click', () => openModal('booking')));
    document.querySelectorAll('[data-open-note]').forEach((button) => button.addEventListener('click', () => openModal('note')));
    document.querySelectorAll('[data-open-customer]').forEach((button) => button.addEventListener('click', () => {
      const fromPicker = Boolean(button.closest('[data-modal="customer-picker"]'));
      const form = customerForm();
      const returnTo = form ? form.querySelector('[name="return_to"]') : null;
      if (fromPicker) {
        rememberBookingForNewCustomer();
        if (returnTo) returnTo.value = 'kalender';
        closeModal(button.closest('.sb-modal'));
      } else if (returnTo) {
        returnTo.value = 'kunden';
      }
      openModal('customer');
    }));
    document.querySelectorAll('[data-open-customer-picker]').forEach((button) => button.addEventListener('click', () => openModal('customer-picker')));
    document.querySelectorAll('[data-close-modal]').forEach((button) => button.addEventListener('click', () => closeModal(button.closest('.sb-modal'))));
    document.querySelectorAll('.sb-modal').forEach((modal) => modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal(modal);
    }));
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      const open = [...document.querySelectorAll('.sb-modal.is-open')].pop();
      if (open) closeModal(open);
    });

    const form = customerForm();
    if (form) {
      form.addEventListener('submit', () => {
        try {
          if (!sessionStorage.getItem(RESUME_BOOKING_KEY)) return;
          const email = form.querySelector('[name="email"]');
          if (email && email.value) sessionStorage.setItem(RESUME_CUSTOMER_EMAIL_KEY, email.value.trim().toLowerCase());
        } catch (_error) {
          // Ignore storage errors and let the normal form submit continue.
        }
      });
    }
  }

  function bindSearch(inputSelector, listSelector) {
    const input = document.querySelector(inputSelector);
    const list = document.querySelector(listSelector);
    if (!input || !list) return;
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll('[data-customer-search]').forEach((item) => {
        const haystack = (item.getAttribute('data-customer-search') || '').toLowerCase();
        item.classList.toggle('is-hidden', Boolean(term) && !haystack.includes(term));
      });
    });
  }

  function selectCustomerButton(button) {
    const hidden = document.querySelector('[data-picked-customer-id]');
    const label = document.querySelector('[data-picked-customer-name]');
    if (hidden) hidden.value = button.getAttribute('data-pick-customer') || '';
    if (label) label.textContent = button.getAttribute('data-customer-name') || 'Kunde ausgewählt';
  }

  function resumeBookingAfterCustomerCreation() {
    let storedState = null;
    let email = '';
    try {
      const raw = sessionStorage.getItem(RESUME_BOOKING_KEY);
      email = sessionStorage.getItem(RESUME_CUSTOMER_EMAIL_KEY) || '';
      if (raw) storedState = JSON.parse(raw);
    } catch (_error) {
      return;
    }
    if (!storedState || !email) return;

    restoreBookingForm(storedState);
    const match = [...document.querySelectorAll('[data-pick-customer]')].find((button) => {
      const haystack = (button.getAttribute('data-customer-search') || '').toLowerCase();
      return haystack.includes(email.toLowerCase());
    });
    if (match) selectCustomerButton(match);

    try {
      sessionStorage.removeItem(RESUME_BOOKING_KEY);
      sessionStorage.removeItem(RESUME_CUSTOMER_EMAIL_KEY);
    } catch (_error) {
      // Ignore cleanup errors.
    }
    openModal('booking');
  }

  function initCustomerPicker() {
    bindSearch('[data-customer-list-search]', '[data-customer-list]');
    bindSearch('[data-customer-picker-search]', '[data-customer-picker-list]');
    document.querySelectorAll('[data-pick-customer]').forEach((button) => button.addEventListener('click', () => {
      selectCustomerButton(button);
      closeModal(button.closest('.sb-modal'));
    }));
    resumeBookingAfterCustomerCreation();
  }

  function initNoteScopes() {
    const serviceRow = document.querySelector('.sb-service-scope-row');
    if (!serviceRow) return;
    const refresh = () => {
      const selected = document.querySelector('input[name="note_scope"]:checked');
      serviceRow.classList.toggle('is-visible', Boolean(selected && selected.value === 'service'));
    };
    document.querySelectorAll('input[name="note_scope"]').forEach((input) => input.addEventListener('change', refresh));
    refresh();
  }

  function initCalendarNoteRefresh() {
    const form = document.querySelector('[data-modal="note"] form');
    if (!form) return;
    form.addEventListener('submit', async (event) => {
      const start = form.querySelector('[name="note_start"]');
      const end = form.querySelector('[name="note_end"]');
      const scope = form.querySelector('input[name="note_scope"]:checked');
      const service = form.querySelector('[name="note_service_id"]');
      if (start && end && start.value && end.value && start.value >= end.value) {
        event.preventDefault();
        window.alert('Die Endzeit muss nach der Startzeit liegen.');
        return;
      }
      if (scope && scope.value === 'service' && service && !service.value) {
        event.preventDefault();
        window.alert('Bitte eine Dienstleistung auswählen.');
        return;
      }
      if (!form.checkValidity()) return;

      event.preventDefault();
      const submitButton = form.querySelector('[type="submit"]');
      if (submitButton) submitButton.disabled = true;
      try {
        const response = await fetch(window.location.href, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const params = new URLSearchParams();
        const date = form.querySelector('[name="return_date"]')?.value || form.querySelector('[name="note_date"]')?.value;
        const view = form.querySelector('[name="return_view"]')?.value || 'day';
        const staff = form.querySelector('[name="staff_id"]')?.value;
        if (date) params.set('date', date);
        if (view) params.set('cal_view', view);
        if (staff) params.set('staff', staff);
        params.set('notice', 'note');
        window.location.assign(`${PAGE_ROUTES.calendar}?${params.toString()}`);
      } catch (error) {
        console.warn('Calendar note submit fallback:', error);
        if (submitButton) submitButton.disabled = false;
        HTMLFormElement.prototype.submit.call(form);
      }
    });
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
    initCalendarNoteRefresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdmin, { once: true });
  } else {
    initAdmin();
  }
})();
