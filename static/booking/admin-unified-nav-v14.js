(() => {
  'use strict';

  // One canonical A+ Management navigation. Customer CRM and patient records now
  // live in one customer area; calendar grid/timeline behaviour is untouched.
  const path = window.location.pathname;

  // Retire the duplicate legacy customer surface without breaking old bookmarks.
  if (/^\/verwaltung\/kunden\/?$/.test(path)) {
    const target = '/verwaltung/app/patients/' + (window.location.search || '');
    window.location.replace(target);
    return;
  }

  const page = (() => {
    if (/^\/verwaltung\/dashboard\/?$/.test(path)) return 'dashboard';
    if (path === '/verwaltung/' || path.includes('/kalender/')) return 'calendar';
    if (path.includes('/buchungen/')) return 'bookings';
    if (path.includes('/app/patients/') || /\/verwaltung\/patienten\//.test(path)) return 'customers';
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
    ['customers', '♙', 'Kunden', '/verwaltung/app/patients/'],
    ['points', '◆', 'A+ Punkte', '/verwaltung/app/wallet/'],
    ['reviews', '★', 'Google Bewertungen', '/verwaltung/app/reviews/'],
    ['referrals', '↗', 'Empfehlungen', '/verwaltung/app/referrals/'],
  ];

  const navMarkup = items
    .map(([key, icon, label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}" data-aplus-nav="${key}"><span>${icon}</span>${label}</a>`)
    .join('');

  const drawer = document.querySelector('[data-drawer]');
  const backdrop = document.querySelector('[data-drawer-backdrop]');
  if (drawer) {
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
      ${navMarkup}
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
  }

  // Desktop uses the same information architecture as mobile.
  document.querySelectorAll('.admin-topbar .admin-nav').forEach(nav => {
    nav.classList.add('aplus-unified-desktop-nav');
    nav.innerHTML = items.map(([key, , label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}">${label}</a>`).join('');
  });

  // Keep page titles coherent, but do not alter the calendar's existing day/week title.
  if (page !== 'calendar') {
    const title = document.querySelector('.sb-mobile-title');
    const titles = {
      dashboard: 'Dashboard',
      bookings: 'Buchungen',
      customers: 'Kunden',
      points: 'A+ Punkte',
      reviews: 'Google Bewertungen',
      referrals: 'Empfehlungen',
    };
    if (title && titles[page]) title.textContent = titles[page];
  }

  if (page !== 'customers') return;

  // Rename the former Patientenakten landing into the single customer CRM.
  const pageHeading = document.querySelector('.app-page-heading');
  if (pageHeading) {
    const h1 = pageHeading.querySelector('h1');
    const p = pageHeading.querySelector('p');
    if (h1) h1.textContent = 'Kunden';
    if (p) p.textContent = 'Kundenprofil, Termine, Patientenakte, Punkte und Kommunikation zentral an einem Ort.';
  }

  const selected = document.querySelector('.patient-command-card');
  if (!selected) {
    const panel = document.querySelector('.app-core-panel');
    const eyebrow = panel?.querySelector('.eyebrow');
    const h2 = panel?.querySelector('h2');
    const p = panel?.querySelector('.panel-head p');
    if (eyebrow) eyebrow.textContent = 'KUNDEN';
    if (h2) h2.textContent = 'Kunden';
    if (p) p.textContent = 'Nachname, Vorname, E-Mail oder Telefon suchen. Ein Profil enthält Termine, Patientenakte, Punkte und Kommunikation.';
    return;
  }

  const back = document.querySelector('.app-back-link');
  if (back) back.textContent = '‹ Alle Kunden';
  const profileLabel = selected.querySelector('.patient-command-copy > span');
  if (profileLabel) profileLabel.textContent = 'KUNDENPROFIL';

  const stats = document.querySelector('.patient-overview-grid');
  const controls = document.querySelector('.patient-control-grid');
  const communication = document.querySelector('.patient-profile-panel');
  const points = document.querySelector('.patient-points-panel');
  const appointments = document.querySelector('.patient-appointments-panel');
  const records = document.querySelector('.app-patient-layout');

  if (!stats || !controls || !communication || !points || !appointments || !records) return;

  const tabs = document.createElement('nav');
  tabs.className = 'customer-profile-tabs';
  tabs.setAttribute('aria-label', 'Kundenprofil Bereiche');
  tabs.innerHTML = `
    <button type="button" data-customer-tab="overview">Übersicht</button>
    <button type="button" data-customer-tab="appointments">Termine</button>
    <button type="button" data-customer-tab="records">Patientenakte</button>
    <button type="button" data-customer-tab="points">Punkte</button>
    <button type="button" data-customer-tab="communication">Kommunikation</button>`;
  selected.insertAdjacentElement('afterend', tabs);

  const show = key => {
    const valid = ['overview', 'appointments', 'records', 'points', 'communication'];
    if (!valid.includes(key)) key = 'overview';

    stats.hidden = key !== 'overview';
    appointments.hidden = key !== 'appointments';
    records.hidden = key !== 'records';

    const controlVisible = key === 'points' || key === 'communication';
    controls.hidden = !controlVisible;
    controls.classList.toggle('is-single-panel', controlVisible);
    points.hidden = key !== 'points';
    communication.hidden = key !== 'communication';

    tabs.querySelectorAll('[data-customer-tab]').forEach(button => {
      const active = button.dataset.customerTab === key;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });

    const hash = key === 'overview' ? '' : `#${key}`;
    history.replaceState(null, '', `${location.pathname}${location.search}${hash}`);
  };

  tabs.addEventListener('click', event => {
    const button = event.target.closest('[data-customer-tab]');
    if (!button) return;
    show(button.dataset.customerTab);
  });

  const initial = (location.hash || '').replace('#', '');
  show(initial || 'overview');
})();
