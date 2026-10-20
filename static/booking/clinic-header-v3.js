(() => {
  'use strict';
  const header = document.querySelector('[data-clinic-header]');
  if (!header) return;
  const details = header.querySelector('.clinic-header-more');
  if (!details) return;
  document.addEventListener('click', e => {
    if (details.open && !details.contains(e.target)) details.open = false;
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && details.open) {
      details.open = false;
      details.querySelector('summary')?.focus();
    }
  });
})();