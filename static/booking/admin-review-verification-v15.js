(() => {
  'use strict';
  if (!window.location.pathname.includes('/verwaltung/app/reviews/')) return;

  const apply = () => {
    document.documentElement.dataset.adminReviewVerification = '1';

    const heading = document.querySelector('.app-page-heading');
    if (heading) {
      const eyebrow = heading.querySelector('.eyebrow');
      const h1 = heading.querySelector('h1');
      const p = heading.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'GOOGLE · DIREKTER REVIEW';
      if (h1) h1.textContent = 'Google Review-Prüfung';
      if (p) p.textContent = 'Kunden schreiben ihre Bewertung direkt bei Google. Hier wird nur bestätigt, dass sie wirklich vorhanden ist, bevor 250 A+ Punkte gutgeschrieben werden.';
    }

    const panel = document.querySelector('.review-admin-list')?.closest('.admin-panel');
    if (panel && !panel.querySelector('.review-direct-info')) {
      const head = panel.querySelector('.panel-head');
      const eyebrow = head?.querySelector('.eyebrow');
      const h2 = head?.querySelector('h2');
      const p = head?.querySelector('p');
      if (eyebrow) eyebrow.textContent = 'INTERNE VERIFIZIERUNG';
      if (h2) h2.textContent = 'Offene Review-Prüfungen';
      if (p) p.textContent = 'Keine Bewertung wird in A+ eingegeben. Der Kunde landet direkt auf Google.';

      const info = document.createElement('div');
      info.className = 'review-direct-info';
      info.innerHTML = '<strong>Direkter Ablauf</strong><span>Google öffnen → Bewertung bei Google abgeben → hier kurz prüfen → +250 Punkte freigeben.</span>';
      head?.insertAdjacentElement('afterend', info);
    }

    // Older app builds logged every tap on the Google button. Until all clients are
    // updated, keep only the newest visible row per customer/email in this queue.
    const seen = new Set();
    document.querySelectorAll('.review-admin-card').forEach(card => {
      const email = (card.querySelector('div > span')?.textContent || '').trim().toLowerCase();
      const name = (card.querySelector('div > strong')?.textContent || '').trim().toLowerCase();
      const key = email || name;
      if (key && seen.has(key)) {
        card.remove();
        return;
      }
      if (key) seen.add(key);

      const form = card.querySelector('form');
      if (!form) return;

      // URL/rating belonged to the retired in-app review form. Verification needs
      // only one explicit confirmation action.
      form.querySelector('input[name="google_review_url"]')?.remove();
      form.querySelector('select[name="rating"]')?.remove();

      const button = form.querySelector('button');
      if (button) {
        button.textContent = 'Bestätigen · +250 Punkte';
        button.classList.add('review-verify-only');
      }

      if (!form.querySelector('.review-check-note')) {
        const note = document.createElement('span');
        note.className = 'review-check-note';
        note.textContent = 'Nur bestätigen, wenn die Google-Bewertung wirklich gefunden wurde.';
        form.prepend(note);
      }
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply, { once: true });
  } else {
    apply();
  }
})();
