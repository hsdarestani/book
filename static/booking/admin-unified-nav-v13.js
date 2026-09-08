(() => {
  'use strict';

  // One canonical A+ Management drawer for every admin surface.
  // This deliberately does not touch calendar grid/timeline behaviour.
  const path = window.location.pathname;
  const page = (() => {
    if (/^\/verwaltung\/dashboard\/?$/.test(path)) return 'dashboard';
    if (path === '/verwaltung/' || path.includes('/kalender/')) return 'calendar';
    if (path.includes('/buchungen/')) return 'bookings';
    if (path.includes('/kunden/')) return 'customers';
    if (/\/verwaltung\/patienten\//.test(path) || path.includes('/app/patients/')) return 'patients';
    if (path.includes('/app/wallet/')) return 'points';
    if (path.includes('/app/reviews/')) return 'reviews';
    if (path.includes('/app/referrals/')) return 'referrals';
    return 'other';
  })();

  if (page !== 'other') document.documentElement.dataset.adminPage = page;

  const items = [
    ['dashboard', '⌂', 'Dashboard', '/verwaltung/dashboard/'],
    ['calendar', '▣', 'Kalender', '/verwaltung/kalender/'],
    ['bookings', '✓', 'Buchungen', '/verwaltung/buchungen/'],
    ['customers', '♙', 'Kunden', '/verwaltung/kunden/'],
    ['patients', '▤', 'Patientenakten', '/verwaltung/app/patients/'],
    ['points', '◆', 'A+ Punkte', '/verwaltung/app/wallet/'],
    ['reviews', '★', 'Google Bewertungen', '/verwaltung/app/reviews/'],
    ['referrals', '↗', 'Empfehlungen', '/verwaltung/app/referrals/'],
  ];

  const drawer = document.querySelector('[data-drawer]');
  const backdrop = document.querySelector('[data-drawer-backdrop]');
  if (!drawer) return;

  drawer.classList.add('aplus-unified-drawer');

  let brand = drawer.querySelector('.sb-drawer-brand');
  if (!brand) {
    brand = document.createElement('div');
    brand.className = 'sb-drawer-brand';
    drawer.prepend(brand);
  }
  brand.innerHTML = '<img src="/static/booking/logo.png" alt="A+ Esthetic"><div><strong>A+ Esthetic</strong><span>Management</span></div>';

  let nav = drawer.querySelector('.sb-drawer-nav');
  if (!nav) {
    nav = document.createElement('nav');
    nav.className = 'sb-drawer-nav';
    drawer.appendChild(nav);
  }
  nav.classList.add('aplus-unified-nav');
  nav.innerHTML = `
    <div class="lux-nav-label">A+ MANAGEMENT</div>
    ${items.map(([key, icon, label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}" data-aplus-nav="${key}"><span>${icon}</span>${label}</a>`).join('')}
    <div class="lux-nav-break"></div>
    <a href="/verwaltung/logout/" data-aplus-nav="logout"><span>↪</span>Abmelden</a>`;

  const closeDrawer = () => {
    drawer.classList.remove('is-open');
    backdrop?.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('drawer-open');
    document.body.classList.remove('drawer-open');
  };
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeDrawer));

  // Keep page titles coherent, but leave the calendar's existing day/week title untouched.
  if (page !== 'calendar') {
    const title = document.querySelector('.sb-mobile-title');
    const titles = {
      dashboard: 'Dashboard',
      bookings: 'Buchungen',
      customers: 'Kunden',
      patients: 'Patientenakten',
      points: 'A+ Punkte',
      reviews: 'Google Bewertungen',
      referrals: 'Empfehlungen',
    };
    if (title && titles[page]) title.textContent = titles[page];
  }
})();
