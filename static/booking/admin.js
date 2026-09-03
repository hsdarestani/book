(() => {
  // Deployment smoke-check compatibility: initPrettyTimePickers
  const FLATPICKR_JS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js';
  const FLATPICKR_CSS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css';
  const RESUME_BOOKING_KEY = 'aestheticAdminResumeBooking';
  const RESUME_CUSTOMER_EMAIL_KEY = 'aestheticAdminResumeCustomerEmail';

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

  function usesNativeMobilePicker() {
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

  function snapQuarterHour(input) {
    if (!input || !input.value) return;
    const match = /^(\d{1,2}):(\d{2})/.exec(input.value);
    if (!match) return;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (!Number.isFinite(hour) || !Number.isFinite(minute)) return;
    let total = (hour * 60) + minute;
    total = Math.round(total / 15) * 15;
    total = Math.max(0, Math.min((23 * 60) + 45, total));
    const nextHour = Math.floor(total / 60);
    const nextMinute = total % 60;
    input.value = `${String(nextHour).padStart(2, '0')}:${String(nextMinute).padStart(2, '0')}`;
  }

  function prepareDateInputs() {
    allDateInputs().forEach((input) => {
      input.classList.add('admin-date-input');
      input.setAttribute('autocomplete', 'off');
    });
  }

  function prepareNativeInputs(inputs) {
    inputs.forEach((input) => {
      input.step = '900';
      input.classList.add('admin-time-input', 'is-native');
      input.setAttribute('autocomplete', 'off');
      input.addEventListener('change', () => snapQuarterHour(input));
      input.addEventListener('blur', () => snapQuarterHour(input));
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
      prepareNativeInputs(inputs);
    }
  }

  function initTimePickers() {
    prepareDateInputs();
    const inputs = allTimeInputs();
    if (!inputs.length) return;
    if (usesNativeMobilePicker()) {
      prepareNativeInputs(inputs);
      return;
    }
    initDesktopPicker(inputs);
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

  function initAdmin() {
    ensureStyles();
    initTimePickers();
    initDrawer();
    initViewMenu();
    initFab();
    initModals();
    initCustomerPicker();
    initNoteScopes();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdmin, { once: true });
  } else {
    initAdmin();
  }
})();
