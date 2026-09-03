(() => {
  // Deployment smoke-check compatibility: initPrettyTimePickers
  const FLATPICKR_JS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.js';
  const FLATPICKR_CSS = 'https://cdn.jsdelivr.net/npm/flatpickr@4.6.13/dist/flatpickr.min.css';

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

  function timeInputs() {
    return [...document.querySelectorAll(
      '.availability-editor input[type="time"], .block-form input[type="time"]'
    )];
  }

  function prepareNativeInputs(inputs) {
    inputs.forEach((input) => {
      input.step = '300';
      input.classList.add('admin-time-input', 'is-native');
    });
  }

  async function initDesktopPicker(inputs) {
    try {
      const flatpickr = await loadFlatpickr();
      if (!flatpickr) throw new Error('Flatpickr unavailable');
      inputs.forEach((input) => {
        input.step = '300';
        input.classList.add('admin-time-input');
        flatpickr(input, {
          enableTime: true,
          noCalendar: true,
          dateFormat: 'H:i',
          time_24hr: true,
          minuteIncrement: 5,
          allowInput: false,
          clickOpens: true,
          disableMobile: true,
          defaultDate: input.value || null,
          position: 'auto center',
          onReady: (_selectedDates, _dateStr, instance) => {
            instance.input.classList.add('is-flatpickr');
            instance.input.setAttribute('autocomplete', 'off');
          },
        });
      });
    } catch (error) {
      console.warn('Desktop time picker fallback:', error);
      prepareNativeInputs(inputs);
    }
  }

  function initTimePickers() {
    const inputs = timeInputs();
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

  function initModals() {
    document.querySelectorAll('[data-open-booking]').forEach((button) => button.addEventListener('click', () => openModal('booking')));
    document.querySelectorAll('[data-open-note]').forEach((button) => button.addEventListener('click', () => openModal('note')));
    document.querySelectorAll('[data-open-customer]').forEach((button) => button.addEventListener('click', () => openModal('customer')));
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
  }

  function bindSearch(inputSelector, listSelector) {
    const input = document.querySelector(inputSelector);
    const list = document.querySelector(listSelector);
    if (!input || !list) return;
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll('[data-customer-search]').forEach((item) => {
        const haystack = (item.getAttribute('data-customer-search') || '').toLowerCase();
        item.classList.toggle('is-hidden', term && !haystack.includes(term));
      });
    });
  }

  function initCustomerPicker() {
    bindSearch('[data-customer-list-search]', '[data-customer-list]');
    bindSearch('[data-customer-picker-search]', '[data-customer-picker-list]');
    const hidden = document.querySelector('[data-picked-customer-id]');
    const label = document.querySelector('[data-picked-customer-name]');
    document.querySelectorAll('[data-pick-customer]').forEach((button) => button.addEventListener('click', () => {
      if (hidden) hidden.value = button.getAttribute('data-pick-customer') || '';
      if (label) label.textContent = button.getAttribute('data-customer-name') || 'Kunde ausgewählt';
      closeModal(button.closest('.sb-modal'));
    }));
  }

  function initNoteScopes() {
    const serviceRow = document.querySelector('.sb-service-scope-row');
    if (!serviceRow) return;
    const refresh = () => {
      const selected = document.querySelector('input[name="note_scope"]:checked');
      serviceRow.classList.toggle('is-visible', selected && selected.value === 'service');
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
