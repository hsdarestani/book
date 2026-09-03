(() => {
  const pad = (value) => String(value).padStart(2, '0');

  function ensureTimePickerStyles() {
    if (document.querySelector('link[data-admin-time-picker]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/booking/admin-time.css';
    link.dataset.adminTimePicker = '1';
    document.head.appendChild(link);
  }

  function addOption(select, value, label) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }

  function enhanceTimeInput(input) {
    if (input.dataset.prettyTime === '1') return;
    input.dataset.prettyTime = '1';

    const required = input.required;
    const initialValue = input.value || '';
    input.required = false;
    input.type = 'hidden';

    const picker = document.createElement('div');
    picker.className = 'pretty-time-picker';

    const icon = document.createElement('span');
    icon.className = 'pretty-time-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '◷';

    const hourSelect = document.createElement('select');
    hourSelect.className = 'pretty-time-select pretty-time-hour';
    hourSelect.setAttribute('aria-label', 'Stunde');
    if (required) hourSelect.required = true;
    addOption(hourSelect, '', 'Std.');
    for (let hour = 0; hour < 24; hour += 1) {
      addOption(hourSelect, pad(hour), pad(hour));
    }

    const separator = document.createElement('span');
    separator.className = 'pretty-time-separator';
    separator.textContent = ':';

    const minuteSelect = document.createElement('select');
    minuteSelect.className = 'pretty-time-select pretty-time-minute';
    minuteSelect.setAttribute('aria-label', 'Minute');
    if (required) minuteSelect.required = true;
    addOption(minuteSelect, '', 'Min.');
    for (let minute = 0; minute < 60; minute += 5) {
      addOption(minuteSelect, pad(minute), pad(minute));
    }

    const currentParts = initialValue.match(/^(\d{2}):(\d{2})/);
    if (currentParts) {
      const [, hour, minute] = currentParts;
      if (![...minuteSelect.options].some((option) => option.value === minute)) {
        addOption(minuteSelect, minute, minute);
      }
      hourSelect.value = hour;
      minuteSelect.value = minute;
    }

    const sync = () => {
      if (hourSelect.value && minuteSelect.value) {
        input.value = `${hourSelect.value}:${minuteSelect.value}`;
        picker.classList.add('has-value');
      } else {
        input.value = '';
        picker.classList.remove('has-value');
      }
      input.dispatchEvent(new Event('change', { bubbles: true }));
    };

    hourSelect.addEventListener('change', sync);
    minuteSelect.addEventListener('change', sync);

    picker.append(icon, hourSelect, separator, minuteSelect);
    input.insertAdjacentElement('afterend', picker);
    sync();
  }

  function initPrettyTimePickers() {
    ensureTimePickerStyles();
    document
      .querySelectorAll('.availability-editor input[type="time"], .block-form input[type="time"]')
      .forEach(enhanceTimeInput);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPrettyTimePickers);
  } else {
    initPrettyTimePickers();
  }
})();
