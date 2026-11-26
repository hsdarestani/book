(() => {
  'use strict';

  const normalize = value => value.normalize('NFC').trim().toLocaleLowerCase('de');

  for (const input of document.querySelectorAll('[data-filter-patient-select]')) {
    const id = input.dataset.filterPatientSelect;
    const select = document.getElementById(id);
    const status = document.querySelector(`[data-patient-search-status="${id}"]`);
    if (!select || !status) continue;

    const update = () => {
      const query = normalize(input.value);
      const digits = /^[+\d\s().-]+$/.test(query) ? query.replace(/\D/g, '') : '';
      let matches = 0;
      for (const option of select.options) {
        if (!option.value) continue;
        const textMatch = normalize(option.textContent).includes(query);
        const phoneMatch = digits && (option.dataset.phone || '').replace(/\D/g, '').includes(digits);
        const match = textMatch || phoneMatch;
        matches += Number(Boolean(match));
        option.hidden = !match && !option.selected;
      }
      status.textContent = query && !matches ? 'Keine passenden Patienten gefunden.' : '';
    };

    input.addEventListener('input', update);
    select.addEventListener('change', update);
  }
})();
