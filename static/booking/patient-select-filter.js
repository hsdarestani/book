(() => {
  'use strict';
  const localSearch = '/verwaltung/api/patient-search/';
  const clean = value => String(value || '').normalize('NFC').trim().toLocaleLowerCase('de');
  const digitize = value => String(value || '').replace(/\D/g, '');
  const make = (tag, className) => { const el = document.createElement(tag); el.className = className; return el; };
  let serial = 0;

  function enhance(select, input, status, extraAction) {
    if (select.dataset.comboboxReady) return;
    select.dataset.comboboxReady = 'true';
    const id = select.id || (select.id = 'clinic-patient-' + ++serial);
    const root = make('div', 'clinic-patient-combobox');
    const trigger = make('button', 'clinic-patient-trigger');
    trigger.type = 'button'; trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-controls', id + '-options');
    const selected = make('span', 'clinic-patient-selected');
    const chevron = make('span', 'clinic-patient-chevron'); chevron.textContent = '⌄'; chevron.setAttribute('aria-hidden', 'true');
    trigger.append(selected, chevron);
    const panel = make('div', 'clinic-patient-panel'); panel.hidden = true;
    if (!input) input = make('input', 'clinic-patient-search');
    else { const oldLabel = input.closest('label'); if (oldLabel) { oldLabel.hidden = true; oldLabel.classList.add('clinic-patient-native'); } }
    input.classList.add('clinic-patient-search'); input.type = 'search'; input.placeholder = 'Name, E-Mail oder Telefon';
    input.autocomplete = 'off'; input.maxLength = 80; input.setAttribute('role', 'combobox');
    input.setAttribute('aria-label', 'Patienten suchen'); input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', id + '-options'); input.setAttribute('aria-expanded', 'false');
    const list = make('div', 'clinic-patient-options'); list.id = id + '-options'; list.setAttribute('role', 'listbox');
    if (!status) status = make('div', 'clinic-patient-status');
    status.classList.add('clinic-patient-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    const more = make('button', 'clinic-patient-more'); more.type = 'button'; more.textContent = 'Weitere Treffer anzeigen'; more.hidden = true;
    panel.append(input, status, list, more);
    if (extraAction) {
      const action = make('button', 'clinic-patient-more'); action.type = 'button'; action.textContent = 'Neuen Patienten hinzufügen';
      action.addEventListener('click', e => { e.preventDefault(); close(); extraAction(); }); panel.append(action);
    }
    root.append(trigger, panel); select.insertAdjacentElement('afterend', root); select.hidden = true;
    select.classList.add('clinic-patient-native'); select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    const url = input.dataset.patientSearchUrl || select.dataset.patientSearchUrl || localSearch;
    const csrf = select.closest('form')?.querySelector('[name="csrfmiddlewaretoken"]');
    let active = -1, resultOptions = [], pending = null, debounce = null, remoteOffset = null, remoteQuery = '';

    function sync() { selected.textContent = select.selectedOptions[0]?.textContent || 'Patient auswählen'; }
    function matches(option, term) {
      const phone = /^[+\d\s()./-]+$/.test(term) && digitize(term);
      return term.split(/\s+/).every(part => clean(option.textContent).includes(part)) ||
        (phone && digitize(option.dataset.phone).includes(phone));
    }
    function show(options, message) {
      list.replaceChildren(); active = -1; resultOptions = options;
      input.removeAttribute('aria-activedescendant');
      options.forEach((option, index) => {
        const item = make('button', 'clinic-patient-option'); item.type = 'button'; item.tabIndex = -1;
        item.id = id + '-option-' + index; item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', String(option.selected));
        item.textContent = option.textContent + (option.dataset.phone ? ' · ' + option.dataset.phone : '');
        item.addEventListener('click', e => { e.preventDefault(); choose(option); }); list.append(item);
      });
      status.textContent = message || (options.length ? options.length + ' passende Patienten' : 'Keine passenden Patienten gefunden.');
    }
    function selectActive(index) {
      active = index; const items = [...list.children];
      items.forEach((item, i) => item.classList.toggle('is-active', i === active));
      if (items[active]) { input.setAttribute('aria-activedescendant', items[active].id); items[active].scrollIntoView({block: 'nearest'}); }
    }
    function choose(option) {
      select.value = option.value; select.dispatchEvent(new Event('input', {bubbles: true}));
      select.dispatchEvent(new Event('change', {bubbles: true})); sync(); close(); trigger.focus();
    }
    function local() {
      const term = clean(input.value); const options = [...select.options].filter(o => o.value && matches(o, term));
      show(options.slice(0, 25), options.length > 25 ? 'Zur vollständigen Suche Namen, E-Mail oder Telefon eingeben.' : '');
    }
    function cancel() { clearTimeout(debounce); pending?.abort(); pending = null; }
    async function search(query, offset = 0) {
      if (!csrf || !url || query.length < 2) return;
      pending?.abort(); const controller = new AbortController(); pending = controller;
      status.textContent = 'Patienten werden gesucht …';
      const timeout = setTimeout(() => controller.abort(), 22000);
      try {
        const response = await fetch(url, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf.value},
          body: JSON.stringify({query, offset}), signal: controller.signal});
        if (!response.ok || response.redirected) throw new Error('Search unavailable');
        const data = await response.json();
        if (!Array.isArray(data.patients) || controller.signal.aborted || query !== input.value.trim() || panel.hidden) return;
        if (!offset) for (const option of select.querySelectorAll('[data-remote-patient]')) if (!option.selected) option.remove();
        const byId = new Map([...select.options].map(option => [option.value, option]));
        const found = offset ? resultOptions.slice() : [];
        for (const patient of data.patients) {
          const value = String(patient.id);
          let option = byId.get(value);
          if (!option) {
            option = new Option([patient.name, patient.birth_date, patient.email && patient.email !== patient.name ? patient.email : ''].filter(Boolean).join(' · '), value);
            option.dataset.remotePatient = ''; select.add(option);
          }
          for (const key of ['phone', 'street', 'postal_code', 'city', 'name', 'email']) {
            if (patient[key] != null) option.dataset[key === 'postal_code' ? 'postalCode' : key] = patient[key];
          }
          if (!found.includes(option)) found.push(option);
        }
        remoteQuery = query; remoteOffset = Number.isInteger(data.next_offset) ? data.next_offset : null;
        more.hidden = remoteOffset == null; show(found);
      } catch (_) {
        if (!controller.signal.aborted && query === input.value.trim()) status.textContent = 'Praxisweite Suche derzeit nicht verfügbar. Lokale Treffer werden angezeigt.';
      } finally { clearTimeout(timeout); if (pending === controller) pending = null; }
    }
    function onSearch() {
      cancel(); more.hidden = true; remoteOffset = null; local();
      const query = input.value.trim(); if (query.length >= 2) debounce = setTimeout(() => search(query), 200);
    }
    function open() {
      if (!panel.hidden) return;
      sync(); panel.hidden = false; trigger.setAttribute('aria-expanded', 'true'); input.setAttribute('aria-expanded', 'true');
      input.value = ''; more.hidden = true; local(); input.focus({preventScroll: true});
    }
    function close() {
      cancel(); panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }
    trigger.addEventListener('click', e => { e.preventDefault(); panel.hidden ? open() : close(); });
    trigger.addEventListener('keydown', e => { if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); open(); selectActive(e.key === 'ArrowDown' ? 0 : resultOptions.length - 1); } });
    input.addEventListener('input', onSearch);
    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); trigger.focus(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); selectActive(Math.max(0, Math.min(resultOptions.length - 1, active + (e.key === 'ArrowDown' ? 1 : -1)))); }
      else if (e.key === 'Home' || e.key === 'End') { if (active !== -1) { e.preventDefault(); selectActive(e.key === 'Home' ? 0 : resultOptions.length - 1); } }
      else if (e.key === 'Enter') { e.preventDefault(); if (resultOptions[active]) choose(resultOptions[active]); }
    });
    more.addEventListener('click', e => { e.preventDefault(); if (remoteOffset != null && !pending) search(remoteQuery, remoteOffset); });
    root.addEventListener('focusout', () => setTimeout(() => { if (!root.contains(document.activeElement)) close(); }, 0));
    document.addEventListener('pointerdown', e => { if (!root.contains(e.target)) close(); });
    select.addEventListener('change', sync); select.addEventListener('invalid', e => { e.preventDefault(); open(); });
    select.closest('form')?.addEventListener('reset', () => setTimeout(sync, 0));
    select.clinicPatientRefresh = sync; sync(); return {sync, open};
  }

  for (const input of document.querySelectorAll('[data-filter-patient-select]')) {
    const id = input.dataset.filterPatientSelect, select = document.getElementById(id);
    if (select) enhance(select, input, document.querySelector('[data-patient-search-status="' + id + '"]'));
  }
  for (const select of document.querySelectorAll('select[data-patient-combobox]')) enhance(select);

  // Upgrade the existing calendar picker without changing its customer creation and resume flow.
  const oldTrigger = document.querySelector('[data-open-customer-picker]');
  const hidden = document.querySelector('[data-picked-customer-id]');
  const picker = document.querySelector('[data-modal="customer-picker"]');
  if (oldTrigger && hidden && picker) {
    const select = document.createElement('select'); select.id = 'bookingPatientPicker';
    select.required = true; select.add(new Option('Patient auswählen', ''));
    for (const item of picker.querySelectorAll('[data-pick-customer]')) {
      const option = new Option([item.dataset.customerName, item.querySelector('small')?.textContent].filter(Boolean).join(' · '), item.dataset.pickCustomer);
      option.dataset.phone = item.dataset.customerPhone || ''; select.add(option);
    }
    oldTrigger.insertAdjacentElement('afterend', select); oldTrigger.hidden = true; oldTrigger.classList.add('clinic-patient-native');
    const label = document.querySelector('[data-picked-customer-name]');
    const control = enhance(select, null, null, () => picker.querySelector('[data-open-customer]')?.click());
    select.addEventListener('change', () => { hidden.value = select.value; if (label) label.textContent = select.selectedOptions[0]?.textContent || 'Patient auswählen'; });
    const sync = () => {
      if (hidden.value && ![...select.options].some(option => option.value === hidden.value)) select.add(new Option(label?.textContent || 'Patient ausgewählt', hidden.value));
      select.value = hidden.value; control.sync();
    };
    const modal = hidden.closest('.sb-modal');
    if (modal) new MutationObserver(sync).observe(modal, {attributes: true, attributeFilter: ['class']});
    sync();
  }
})();
