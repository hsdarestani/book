(() => {
  'use strict';
  const search = document.querySelector('[data-clinic-service-search]');
  const list = document.querySelector('[data-clinic-service-list]');
  if (!search || !list) return;
  const items = [...list.querySelectorAll('[data-clinic-service-card]')];
  const count = document.querySelector('[data-clinic-service-count]');
  const empty = document.querySelector('[data-clinic-service-empty]');
  const refresh = () => {
    const term = (search.value || '').trim().toLocaleLowerCase('de').normalize('NFKD');
    let visible = 0;
    for (const el of items) {
      const haystack = String(el.dataset.clinicServiceName || '').toLocaleLowerCase('de').normalize('NFKD');
      const match = !term || haystack.includes(term);
      el.hidden = !match;
      if (match) visible++;
    }
    if (count) count.textContent = visible + ' von ' + items.length + ' Behandlungen';
    if (empty) empty.hidden = visible !== 0;
  };
  search.addEventListener('input', refresh);
  refresh();
})();