(() => {
  'use strict';

  const normalize = value => value.normalize('NFC').trim().toLocaleLowerCase('de');

  for (const input of document.querySelectorAll('[data-filter-patient-select]')) {
    const id = input.dataset.filterPatientSelect;
    const select = document.getElementById(id);
    const status = document.querySelector(`[data-patient-search-status="${id}"]`);
    if (!select || !status) continue;

    let remoteQuery = '';
    let remoteIds = new Set();

    const update = () => {
      const query = normalize(input.value);
      const digits = /^[+\d\s().-]+$/.test(query) ? query.replace(/\D/g, '') : '';
      let matches = 0;
      for (const option of select.options) {
        if (!option.value) continue;
        const textMatch = normalize(option.textContent).includes(query);
        const phoneMatch = digits && (option.dataset.phone || '').replace(/\D/g, '').includes(digits);
        const match = textMatch || phoneMatch || (remoteQuery === query && remoteIds.has(option.value));
        matches += Number(Boolean(match));
        option.hidden = !match && !option.selected;
      }
      status.textContent = query && !matches ? 'Keine passenden Patienten gefunden.' : '';
    };

    const url = input.dataset.patientSearchUrl;
    const csrf = input.closest('form')?.querySelector('[name="csrfmiddlewaretoken"]');
    let debounce;
    let pending;
    const search = () => {
      clearTimeout(debounce);
      pending?.abort();
      update();
      const query = input.value.trim();
      if (!url || !csrf || query.length < 2) return;
      status.textContent = 'Patienten werden gesucht …';
      debounce = setTimeout(async () => {
        const controller = new AbortController();
        pending = controller;
        const timeout = setTimeout(() => controller.abort(), 22000);
        try {
          const response = await fetch(url, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf.value},
            body: JSON.stringify({query}), signal: controller.signal,
          });
          if (!response.ok || response.redirected) throw new Error('Search unavailable');
          const data = await response.json();
          if (controller.signal.aborted || query !== input.value.trim()) return;
          for (const option of select.querySelectorAll('[data-remote-patient]')) {
            if (!option.selected) option.remove();
          }
          remoteQuery = normalize(query);
          remoteIds = new Set(data.patients.map(item => String(item.id)));
          const existing = new Set([...select.options].map(option => option.value));
          for (const item of data.patients) {
            const value = String(item.id);
            if (existing.has(value)) continue;
            const label = item.email && item.name !== item.email ? `${item.name} · ${item.email}` : item.name;
            const option = new Option(label, value);
            option.dataset.remotePatient = '';
            select.add(option);
          }
          update();
          if (data.patients.length) status.textContent = `${data.patients.length} passende Patienten`;
        } catch (_) {
          if (query === input.value.trim() && pending === controller) {
            status.textContent = 'Praxisweite Suche derzeit nicht verfügbar. Lokale Treffer werden angezeigt.';
          }
        } finally {
          clearTimeout(timeout);
          if (pending === controller) pending = null;
        }
      }, 230);
    };
    input.addEventListener('input', search);
    select.addEventListener('change', update);
  }
})();
