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

  // Google review management used to expose the raw event log and manual
  // verification fields as the primary UI. Keep the data, but turn it into a
  // patient-level review center and move manual verification behind details.
  if (page === 'reviews') {
    const panel = document.querySelector('.app-core-panel');
    const list = panel?.querySelector('.app-card-list');
    const cards = list ? [...list.querySelectorAll('.app-review-card')] : [];

    if (panel && list) {
      const parseCard = card => {
        const head = card.querySelector('.app-review-head');
        const name = head?.querySelector('strong')?.textContent.trim() || 'Patient';
        const email = head?.querySelector('span')?.textContent.trim() || name;
        const status = head?.querySelector('.app-status')?.textContent.trim() || 'Aktivität';
        const statusClass = [...(head?.querySelector('.app-status')?.classList || [])].find(value => value.startsWith('is-')) || '';
        const meta = card.querySelector('.app-review-meta');
        const rating = meta?.querySelector('b')?.textContent.trim() || 'Keine Sterne gespeichert';
        const rawDate = meta?.querySelector('span')?.textContent.trim() || '';
        return { card, name, email, status, statusClass, rating, rawDate };
      };

      const entries = cards.map(parseCard);
      const groups = new Map();
      entries.forEach(entry => {
        const key = entry.email.toLowerCase();
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(entry);
      });

      const verifiedCount = entries.filter(entry => entry.statusClass === 'is-verified' || /geprüft|verifiziert/i.test(entry.status)).length;
      const submittedCount = entries.filter(entry => /abgegeben|submitted|eingereicht/i.test(entry.status)).length;
      const openedCount = entries.filter(entry => /geöffnet|opened/i.test(entry.status)).length;

      const oldHead = panel.querySelector('.panel-head');
      if (oldHead) oldHead.remove();

      const hero = document.createElement('section');
      hero.className = 'lux-review-hero';
      hero.innerHTML = `
        <div class="lux-review-hero-copy">
          <span>GOOGLE REVIEW CENTER</span>
          <h2>Bewertungen im Blick</h2>
          <p>Hier siehst du, wer den Google-Bewertungsflow aus der App geöffnet oder als abgegeben markiert hat. Das ist Aktivitäts-Tracking – keine Live-Liste aus Google.</p>
        </div>
        <div class="lux-review-mark">★</div>`;
      panel.prepend(hero);

      const metrics = document.createElement('div');
      metrics.className = 'lux-review-metrics';
      metrics.innerHTML = `
        <article><span>Patienten</span><strong>${groups.size}</strong><small>mit Aktivität</small></article>
        <article><span>Geöffnet</span><strong>${openedCount}</strong><small>Google-Link geöffnet</small></article>
        <article><span>Abgegeben</span><strong>${submittedCount}</strong><small>in der App markiert</small></article>
        <article><span>Geprüft</span><strong>${verifiedCount}</strong><small>manuell bestätigt</small></article>`;
      hero.after(metrics);

      groups.forEach(group => {
        // API is newest-first. Prefer a meaningful submitted/verified event over a
        // plain open event when both exist, then keep the rest as compact history.
        const primary = group.find(entry => entry.statusClass === 'is-verified' || /geprüft|verifiziert/i.test(entry.status))
          || group.find(entry => /abgegeben|submitted|eingereicht/i.test(entry.status))
          || group[0];
        const older = group.filter(entry => entry !== primary);
        const card = primary.card;
        card.classList.add('lux-review-card');

        const head = card.querySelector('.app-review-head');
        if (head && !head.querySelector('.lux-review-avatar')) {
          const avatar = document.createElement('div');
          avatar.className = 'lux-review-avatar';
          avatar.textContent = (primary.name || 'P').trim().charAt(0).toUpperCase();
          head.prepend(avatar);
        }

        const meta = card.querySelector('.app-review-meta');
        if (meta) {
          meta.classList.add('lux-review-meta');
          const dateNode = meta.querySelector('span');
          if (dateNode && primary.rawDate) {
            const parsed = new Date(primary.rawDate);
            if (!Number.isNaN(parsed.getTime())) {
              dateNode.textContent = new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
            }
          }
        }

        const form = card.querySelector('.app-review-form');
        if (form) {
          const details = document.createElement('details');
          details.className = 'lux-review-verify';
          const summary = document.createElement('summary');
          summary.textContent = 'Manuell prüfen';
          details.append(summary, form);
          card.appendChild(details);
        }

        if (older.length) {
          const details = document.createElement('details');
          details.className = 'lux-review-history';
          const summary = document.createElement('summary');
          summary.textContent = `${older.length} weitere Aktivität${older.length === 1 ? '' : 'en'}`;
          const history = document.createElement('div');
          history.className = 'lux-review-history-list';
          older.forEach(entry => {
            const row = document.createElement('div');
            row.innerHTML = `<span class="${entry.statusClass}">${entry.status}</span><b>${entry.rating}</b><small>${entry.rawDate}</small>`;
            history.appendChild(row);
            entry.card.remove();
          });
          details.append(summary, history);
          card.appendChild(details);
        }
      });

      if (!cards.length) {
        list.classList.add('lux-review-empty-list');
      }
    }

    if (!document.getElementById('aplus-review-center-style')) {
      const style = document.createElement('style');
      style.id = 'aplus-review-center-style';
      style.textContent = `
        html[data-admin-page="reviews"] .app-page-heading{display:none!important}
        html[data-admin-page="reviews"] .app-core-panel{background:transparent!important;border:0!important;box-shadow:none!important;overflow:visible!important;padding:18px 0 40px!important}
        .lux-review-hero{display:grid!important;grid-template-columns:1fr auto!important;gap:18px!important;align-items:center!important;padding:28px!important;border-radius:28px!important;background:radial-gradient(circle at 92% 0,rgba(219,177,92,.22),transparent 34%),linear-gradient(145deg,#2c2922,#171612)!important;color:#fff!important;box-shadow:0 22px 55px rgba(35,28,18,.18)!important}
        .lux-review-hero-copy>span{display:block!important;color:#e4c47f!important;font-size:9px!important;font-weight:850!important;letter-spacing:.19em!important;margin-bottom:8px!important}
        .lux-review-hero h2{margin:0!important;color:#fff!important;font-size:clamp(29px,8vw,44px)!important;letter-spacing:-.045em!important;line-height:1!important}
        .lux-review-hero p{max-width:650px!important;margin:12px 0 0!important;color:rgba(255,255,255,.62)!important;font-size:13px!important;line-height:1.55!important}
        .lux-review-mark{width:62px!important;height:62px!important;border-radius:20px!important;display:grid!important;place-items:center!important;background:linear-gradient(145deg,#e2bd6b,#bd8731)!important;color:#231d14!important;font-size:27px!important;box-shadow:0 12px 30px rgba(180,129,40,.22)!important}
        .lux-review-metrics{display:grid!important;grid-template-columns:repeat(4,1fr)!important;gap:10px!important;margin:14px 0 18px!important}
        .lux-review-metrics article{padding:16px!important;border:1px solid rgba(62,50,31,.11)!important;border-radius:20px!important;background:rgba(255,255,255,.94)!important;box-shadow:0 8px 24px rgba(48,37,20,.045)!important}
        .lux-review-metrics span{display:block!important;color:#9a7737!important;font-size:9px!important;font-weight:800!important;letter-spacing:.12em!important;text-transform:uppercase!important}
        .lux-review-metrics strong{display:block!important;margin:6px 0 2px!important;color:#211f1a!important;font-size:26px!important;line-height:1!important}
        .lux-review-metrics small{color:#968e81!important;font-size:10px!important}
        html[data-admin-page="reviews"] .app-card-list{display:grid!important;gap:12px!important}
        html[data-admin-page="reviews"] .app-review-card.lux-review-card{padding:20px!important;border:1px solid rgba(62,50,31,.12)!important;border-radius:24px!important;background:#fff!important;box-shadow:0 10px 30px rgba(48,37,20,.055)!important}
        html[data-admin-page="reviews"] .app-review-head{display:grid!important;grid-template-columns:48px 1fr auto!important;gap:12px!important;align-items:center!important}
        .lux-review-avatar{width:48px!important;height:48px!important;border-radius:16px!important;display:grid!important;place-items:center!important;background:linear-gradient(145deg,#2c2922,#171612)!important;color:#e5c47f!important;font:700 18px Georgia,serif!important}
        html[data-admin-page="reviews"] .app-review-head>div:not(.lux-review-avatar){min-width:0!important}
        html[data-admin-page="reviews"] .app-review-head strong{display:block!important;color:#211f1a!important;font-size:15px!important;line-height:1.25!important}
        html[data-admin-page="reviews"] .app-review-head span:not(.app-status){display:block!important;margin-top:3px!important;color:#948c7f!important;font-size:10px!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important}
        html[data-admin-page="reviews"] .app-review-head .app-status{padding:7px 10px!important;border-radius:999px!important;font-size:9px!important;font-weight:800!important;white-space:nowrap!important}
        .lux-review-meta{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:10px!important;margin:15px 0 0!important;padding:12px 14px!important;border-radius:16px!important;background:#f8f5ee!important}
        .lux-review-meta b{font-size:12px!important;color:#6c5227!important}.lux-review-meta span{font-size:10px!important;color:#948c7f!important}
        html[data-admin-page="reviews"] .app-review-card>p{margin:12px 2px 0!important;padding:12px 14px!important;border-left:3px solid #d2aa5e!important;border-radius:0 14px 14px 0!important;background:#fbf8f0!important;color:#554e43!important;font-size:12px!important;line-height:1.55!important}
        .lux-review-verify,.lux-review-history{margin-top:13px!important;border-top:1px solid rgba(62,50,31,.09)!important;padding-top:12px!important}
        .lux-review-verify summary,.lux-review-history summary{cursor:pointer!important;list-style:none!important;color:#705a34!important;font-size:11px!important;font-weight:800!important}
        .lux-review-verify summary::-webkit-details-marker,.lux-review-history summary::-webkit-details-marker{display:none!important}
        .lux-review-verify summary::after,.lux-review-history summary::after{content:'＋';float:right!important;color:#b08741!important;font-size:16px!important;font-weight:400!important}
        .lux-review-verify[open] summary::after,.lux-review-history[open] summary::after{content:'−'}
        html[data-admin-page="reviews"] .app-review-form{margin-top:12px!important;padding:14px!important;border-radius:17px!important;background:#f8f5ee!important;display:grid!important;grid-template-columns:1fr 2fr!important;gap:10px!important}
        html[data-admin-page="reviews"] .app-review-form label{font-size:10px!important;color:#7b725f!important;font-weight:700!important}
        html[data-admin-page="reviews"] .app-review-form input{width:100%!important;min-height:46px!important;margin-top:5px!important;border:1px solid rgba(62,50,31,.12)!important;border-radius:13px!important;background:#fff!important;padding:0 12px!important;box-sizing:border-box!important}
        html[data-admin-page="reviews"] .app-review-form button{grid-column:1/-1!important;min-height:48px!important;border:0!important;border-radius:14px!important;background:#25221c!important;color:#fff!important;font-weight:800!important}
        .lux-review-history-list{display:grid!important;gap:7px!important;margin-top:10px!important}.lux-review-history-list>div{display:grid!important;grid-template-columns:auto 1fr auto!important;gap:8px!important;align-items:center!important;padding:10px 12px!important;border-radius:13px!important;background:#f8f5ee!important}.lux-review-history-list span{font-size:9px!important;font-weight:800!important;color:#7d6842!important}.lux-review-history-list b{font-size:10px!important;color:#423b31!important}.lux-review-history-list small{font-size:9px!important;color:#9b9387!important}
        @media(max-width:700px){.lux-review-metrics{grid-template-columns:repeat(2,1fr)!important}.lux-review-hero{padding:22px!important}.lux-review-mark{width:52px!important;height:52px!important;border-radius:17px!important}.lux-review-hero p{font-size:12px!important}html[data-admin-page="reviews"] .app-review-form{grid-template-columns:1fr!important}html[data-admin-page="reviews"] .app-review-form button{grid-column:auto!important}}
      `;
      document.head.appendChild(style);
    }
  }
})();
