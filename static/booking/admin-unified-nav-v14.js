(() => {
  'use strict';

  // One canonical A+ Management navigation. Customer CRM and patient records now
  // live in one customer area; calendar grid/timeline behaviour is untouched.
  const path = window.location.pathname;
  // Doctor and full admin intentionally share this exact navigation component.
  // The server remains the authority for clinician access, but inaccessible
  // management pages should never be offered as navigation choices.
  const doctorRole = document.documentElement.dataset.doctorRole === '1'
    || document.body?.dataset.doctorCalendar === '1';
  const doctorSection = new URLSearchParams(window.location.search).get('section') || 'calendar';
  const doctorItems = [
    ['dashboard', '⌂', 'Dashboard', '/verwaltung/arzt/?section=dashboard'],
    ['calendar', '▣', 'Kalender', '/verwaltung/arzt/?section=calendar'],
    ['bookings', '▤', 'Meine Buchungen', '/verwaltung/arzt/?section=bookings'],
    ['customers', '♙', 'Meine Patienten', '/verwaltung/arzt/?section=customers'],
    ['settings', '◷', 'Arbeitszeiten', '/verwaltung/arzt/?section=settings'],
  ];

  // Retire the duplicate legacy customer surface without breaking old bookmarks.
  if (/^\/verwaltung\/kunden\/?$/.test(path)) {
    const target = '/verwaltung/app/patients/' + (window.location.search || '');
    window.location.replace(target);
    return;
  }

  const page = (() => {
    if (doctorRole) {
      if (/^\/verwaltung\/patienten\//.test(path)) return 'customers';
      return doctorItems.some(([key]) => key === doctorSection) ? doctorSection : 'calendar';
    }
    if (/^\/verwaltung\/dashboard\/?$/.test(path)) return 'dashboard';
    if (path === '/verwaltung/' || path.includes('/kalender/')) return 'calendar';
    if (path.includes('/app/patients/') || /\/verwaltung\/patienten\//.test(path)) return 'customers';
    if (path.includes('/app/wallet/')) return 'points';
    if (path.includes('/app/reviews/')) return 'reviews';
    if (path.includes('/app/forms/')) return 'forms';
    if (path.includes('/einstellungen/')) return 'settings';
    if (path.includes('/app/referrals/')) return 'referrals';
    if (path.includes('/app/hero/')) return 'hero';
    if (path.includes('/app/invoices/')) return 'invoices';
    if (path.includes('/mehr/')) return location.hash === '#campaigns' ? 'campaigns' : 'more';
    return 'other';
  })();

  if (page !== 'other') {
    document.documentElement.dataset.adminPage = !doctorRole && page === 'customers'
      ? 'patients'
      : !doctorRole && page === 'points' ? 'wallet' : page === 'campaigns' ? 'more' : page;
  }

  const items = doctorRole ? doctorItems : [
    ['dashboard', '⌂', 'Dashboard', '/verwaltung/dashboard/'],
    ['calendar', '▣', 'Kalender', '/verwaltung/kalender/'],
    ['customers', '♙', 'Patienten & Akten', '/verwaltung/app/patients/'],
    ['forms', '▤', 'Aufnahmebögen', '/verwaltung/app/forms/'],
    ['invoices', '▧', 'Rechnungen', '/verwaltung/app/invoices/'],
    ['points', '◆', 'A+ Punkte', '/verwaltung/app/wallet/'],

    ['referrals', '↗', 'Empfehlungen', '/verwaltung/app/referrals/'],
    ['hero', '▧', 'Startseitenbilder', '/verwaltung/app/hero/'],
    ['campaigns', '▤', 'Kampagnen', '/verwaltung/mehr/#campaigns'],
    ['more', '⋯', 'WhatsApp-Vorlagen', '/verwaltung/mehr/#whatsapp-templates'],
    ['settings', '◷', 'Einstellungen', '/verwaltung/einstellungen/'],
  ];

  const navMarkup = items
    .map(([key, icon, label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}"${page === key ? ' aria-current="page"' : ''} data-aplus-nav="${key}"><span>${icon}</span>${label}</a>`)
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
    brand.innerHTML = '<img src="/static/booking/logo.png" alt="A+ Esthetic"><div><strong>A+ Esthetic</strong><span>' + (doctorRole ? 'DOCTOR' : 'Management') + '</span></div>';

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
    nav.innerHTML = items.map(([key, , label, href]) => `<a href="${href}" class="${page === key ? 'is-active' : ''}"${page === key ? ' aria-current="page"' : ''}>${label}</a>`).join('');
  });

  // Keep page titles coherent, but do not alter the calendar's existing day/week title.
  if (page !== 'calendar') {
    const title = document.querySelector('.sb-mobile-title');
    const titles = {
      dashboard: 'Dashboard',
      customers: doctorRole ? 'Meine Patienten' : 'Patienten & Akten',
      bookings: 'Meine Buchungen',
      settings: doctorRole ? 'Arbeitszeiten' : 'Einstellungen',
      forms: 'Aufnahmebögen',
      points: 'A+ Punkte',
      reviews: 'Google Bewertungen',
      referrals: 'Empfehlungen',
      invoices: 'Rechnungen',
      hero: 'Startseitenbilder',
      campaigns: 'Kampagnen',
      more: 'Kampagnen & Vorlagen',
    };
    if (title && titles[page]) title.textContent = titles[page];
  }

  if (page !== 'customers') return;

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

  const tabs = document.querySelector('.customer-profile-tabs');
  const stats = document.querySelector('.patient-overview-grid');
  const controls = document.querySelector('[data-customer-control-grid]');
  const communication = document.querySelector('.patient-profile-panel');
  const points = document.querySelector('.patient-points-panel');
  const appointments = document.querySelector('.patient-appointments-panel');
  const records = document.querySelector('.app-patient-layout');

  if (!tabs || !stats || !controls || !communication || !points || !appointments || !records) return;

  const show = rawKey => {
    const valid = ['overview', 'appointments', 'records', 'points'];
    const key = valid.includes(rawKey) ? rawKey : 'overview';

    document.querySelectorAll('[data-customer-panel]').forEach(panel => {
      const panelKey = panel.dataset.customerPanel;
      const visible =
        panelKey === key ||
        (key === 'overview' && panelKey === 'overview');
      panel.classList.toggle('is-tab-hidden', !visible);
      panel.hidden = !visible;
      panel.setAttribute('aria-hidden', visible ? 'false' : 'true');
    });

    const controlVisible = key === 'overview' || key === 'points';
    controls.classList.toggle('is-tab-hidden', !controlVisible);
    controls.hidden = !controlVisible;
    controls.classList.add('is-single-panel');

    communication.classList.toggle('is-tab-hidden', key !== 'overview');
    communication.hidden = key !== 'overview';
    points.classList.toggle('is-tab-hidden', key !== 'points');
    points.hidden = key !== 'points';

    tabs.querySelectorAll('[data-customer-tab]').forEach(button => {
      const active = button.dataset.customerTab === key;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });

    const hash = key === 'overview' ? '' : `#${key}`;
    history.replaceState(null, '', `${location.pathname}${location.search}${hash}`);
  };

  tabs.addEventListener('click', event => {
    const button = event.target.closest('[data-customer-tab]');
    if (!button) return;
    show(button.dataset.customerTab);
    requestAnimationFrame(() => {
      const top = tabs.getBoundingClientRect().top + window.scrollY - 72;
      window.scrollTo({top: Math.max(0, top), behavior: 'smooth'});
    });
  });

  window.addEventListener('hashchange', () => {
    show((location.hash || '').replace('#', '') || 'overview');
  });

  show((location.hash || '').replace('#', '') || 'overview');
})();
