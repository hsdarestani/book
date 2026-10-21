(() => {
  'use strict';
  const header = document.querySelector('[data-clinic-header]');
  if (!header) return;
  // Shared active state is derived from real links, for the calendar too.
  const currentPath = location.pathname === '/verwaltung/' ? '/verwaltung/kalender/' : location.pathname;
  header.querySelectorAll('a[data-clinic-page]').forEach(link => {
    const active = new URL(link.href, location.href).pathname === currentPath;
    link.classList.toggle('is-active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
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