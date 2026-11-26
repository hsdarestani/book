/* Locale-independent display, with the original ISO date control kept for
   the server and the browser's native date picker. Calendar/GOÄ use their
   own specialised controllers and are deliberately not changed here. */
(() => {
  'use strict';
  const page = document.documentElement.dataset.adminPage;
  if (!page || ['calendar', 'doctor', 'invoices'].includes(page)) return;
  const show = iso => /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : '';
  const parse = text => {
    const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(text.trim());
    if (!match) return '';
    const iso = `${match[3]}-${match[2]}-${match[1]}`;
    const probe = document.createElement('input'); probe.type = 'date'; probe.value = iso;
    return probe.value === iso ? iso : '';
  };
  for (const source of document.querySelectorAll('input[type="date"]:not([data-native-date])')) {
    if (source.closest('.clinic-german-field') || source.hidden) continue;
    const wrap = document.createElement('span'); wrap.className = 'clinic-german-field';
    const display = document.createElement('input'); display.type = 'text'; display.inputMode = 'numeric';
    display.className = 'clinic-german-display'; display.placeholder = 'TT.MM.JJJJ'; display.maxLength = 10;
    display.required = source.required; display.disabled = source.disabled; display.readOnly = source.readOnly;
    const label = source.labels?.[0]?.textContent?.trim() || source.getAttribute('aria-label') || 'Datum';
    display.setAttribute('aria-label', label); display.value = show(source.value);
    const picker = document.createElement('button'); picker.type = 'button'; picker.className = 'clinic-german-picker';
    picker.textContent = '▦'; picker.setAttribute('aria-label', `${label}: Kalender öffnen`); picker.disabled = source.disabled || source.readOnly;
    source.before(wrap); wrap.append(display, source, picker); source.classList.add('clinic-german-source');
    source.required = false; source.tabIndex = -1; source.setAttribute('aria-hidden', 'true');
    const sync = () => { display.value = show(source.value); display.setCustomValidity(''); };
    source.addEventListener('change', sync);
    display.addEventListener('input', () => {
      const entered = display.value.trim(); const iso = parse(entered); source.value = iso;
      let valid = !entered || Boolean(iso);
      if (iso && (source.min && iso < source.min || source.max && iso > source.max)) valid = false;
      display.setCustomValidity(valid ? '' : 'Bitte ein gültiges Datum im Format TT.MM.JJJJ eingeben.');
      if (valid) source.dispatchEvent(new Event('input', {bubbles:true}));
    });
    display.addEventListener('change', () => { if (display.checkValidity()) source.dispatchEvent(new Event('change',{bubbles:true})); });
    picker.addEventListener('click', () => { try { source.showPicker(); } catch (_) { display.focus(); } });
    source.form?.addEventListener('reset', () => requestAnimationFrame(sync));
  }
})();
