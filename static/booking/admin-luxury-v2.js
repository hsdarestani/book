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

  // Replace the raw browser file control in the focused Patientenakte with a
  // premium drop/tap surface while preserving the original input and form.
  document.querySelectorAll('.app-patient-upload input[type="file"]').forEach(input => {
    if (input.dataset.luxFile) return;
    input.dataset.luxFile = '1';
    const label = input.closest('label');
    if (!label) return;
    label.classList.add('lux-file-field');
    const face = document.createElement('span');
    face.className = 'lux-file-face';
    face.innerHTML = '<b>＋</b><strong>Datei auswählen</strong><small>Foto, PDF oder Dokument · antippen zum Auswählen</small>';
    input.before(face);
    const strong = face.querySelector('strong');
    const small = face.querySelector('small');
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (!file) {
        strong.textContent = 'Datei auswählen';
        small.textContent = 'Foto, PDF oder Dokument · antippen zum Auswählen';
        return;
      }
      strong.textContent = file.name;
      small.textContent = `${Math.max(1, Math.round(file.size / 1024))} KB · bereit zum Speichern`;
    });
  });

  if (!document.getElementById('aplus-lux-file-style')) {
    const style = document.createElement('style');
    style.id = 'aplus-lux-file-style';
    style.textContent = `
      .app-patient-upload .lux-file-field{position:relative!important;display:block!important;overflow:hidden!important;border:1px dashed rgba(164,126,57,.35)!important;border-radius:19px!important;background:#faf6eb!important;padding:0!important;min-height:118px!important;color:transparent!important}
      .app-patient-upload .lux-file-field input[type=file]{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;opacity:0!important;cursor:pointer!important;padding:0!important;z-index:2!important}
      .app-patient-upload .lux-file-face{position:absolute!important;inset:0!important;display:grid!important;place-items:center!important;align-content:center!important;gap:4px!important;text-align:center!important;padding:16px!important;box-sizing:border-box!important;color:#74684f!important;pointer-events:none!important}
      .app-patient-upload .lux-file-face b{width:34px!important;height:34px!important;border-radius:12px!important;display:grid!important;place-items:center!important;background:#e7c77f!important;color:#2b2419!important;font-size:20px!important}
      .app-patient-upload .lux-file-face strong{max-width:90%!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;color:#29261f!important;font-size:14px!important}
      .app-patient-upload .lux-file-face small{color:#928873!important;font-size:10px!important;font-weight:500!important}
    `;
    document.head.appendChild(style);
  }
})();
