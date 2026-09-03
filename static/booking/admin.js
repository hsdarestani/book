(() => {
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
    ensureStyles();
    const inputs = timeInputs();
    if (!inputs.length) return;

    if (usesNativeMobilePicker()) {
      prepareNativeInputs(inputs);
      return;
    }

    initDesktopPicker(inputs);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTimePickers, { once: true });
  } else {
    initTimePickers();
  }
})();
