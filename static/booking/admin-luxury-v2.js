(() => {
  'use strict';

  const path = window.location.pathname;
  const page = (() => {
    if (path.includes('/kalender/')) return 'calendar';
    if (path.includes('/buchungen/')) return 'bookings';
    if (path.includes('/kunden/')) return 'customers';
    if (/\/verwaltung\/patienten\//.test(path) || path.includes('/app/patients/')) return 'patients';
    if (path.includes('/app/wallet/')) return 'wallet';
    if (path.includes('/app/reviews/')) return 'reviews';
    if (path.includes('/app/referrals/')) return 'referrals';
    if (path.includes('/einstellungen/')) return 'settings';
    if (path.includes('/behandlungen/')) return 'services';
    if (path.includes('/information/')) return 'information';
    return 'calendar';
  })();

  document.documentElement.dataset.adminPage = page;

  const items = [
    ['calendar', '▣', 'Kalender', '/verwaltung/kalender/'],
    ['bookings', '✓', 'Buchungen', '/verwaltung/buchungen/'],
    ['customers', '♙', 'Kunden', '/verwaltung/kunden/'],
    ['patients', '▤', 'Patientenakten', '/verwaltung/app/patients/'],
    ['wallet', '€', 'A+ Wallet', '/verwaltung/app/wallet/'],
    ['reviews', '★', 'Google Bewertungen', '/verwaltung/app/reviews/'],
    ['referrals', '↗', 'Empfehlungen', '/verwaltung/app/referrals/'],
  ];

  const drawer = document.querySelector('[data-drawer]');
  const backdrop = document.querySelector('[data-drawer-backdrop]');
  if (drawer) {
    const brand = drawer.querySelector('.sb-drawer-brand');
    if (brand) {
      const img = brand.querySelector('img');
      if (img) {
        img.src = '/static/booking/logo.png';
        img.removeAttribute('srcset');
      }
      const strong = brand.querySelector('strong');
      const span = brand.querySelector('span');
      if (strong) strong.textContent = 'A+ Esthetic';
      if (span) span.textContent = 'Management';
    }

    const nav = drawer.querySelector('.sb-drawer-nav');
    if (nav) {
      nav.innerHTML = `
        <div class="lux-nav-label">A+ MANAGEMENT</div>
        ${items.map(([key, icon, label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}"><span>${icon}</span>${label}</a>`).join('')}
        <div class="lux-nav-break"></div>
        <a href="/verwaltung/logout/"><span>↪</span>Abmelden</a>`;
      nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
        drawer.classList.remove('is-open');
        backdrop?.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
      }));
    }
  }

  // The three-dot view switcher belongs exclusively to the calendar.
  if (page !== 'calendar') {
    document.querySelectorAll('[data-view-menu-open]').forEach(node => node.remove());
    document.querySelectorAll('[data-view-menu]').forEach(node => node.remove());
  }

  const title = document.querySelector('.sb-mobile-title');
  const titles = {
    calendar: 'Kalender',
    bookings: 'Buchungen',
    customers: 'Kunden',
    patients: 'Patientenakten',
    wallet: 'A+ Wallet',
    reviews: 'Google Bewertungen',
    referrals: 'Empfehlungen',
    settings: 'Einstellungen',
    services: 'Dienstleistungen',
    information: 'Information',
  };
  if (title && page !== 'calendar') title.textContent = titles[page] || 'Verwaltung';

  // Give raw patient upload controls a proper mobile affordance without changing form behavior.
  document.querySelectorAll('.app-patient-upload input[type="file"]').forEach(input => {
    if (input.dataset.luxFile) return;
    input.dataset.luxFile = '1';
    input.addEventListener('change', () => {
      const label = input.closest('label');
      if (!label || !input.files?.length) return;
      label.dataset.filename = input.files[0].name;
    });
  });
})();
