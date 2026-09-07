(() => {
  'use strict';

  const closeHistory = () => {
    document.querySelector('.v3-wallet-history-overlay')?.remove();
    document.documentElement.style.overflow = '';
  };

  const openHistory = async href => {
    closeHistory();
    const overlay = document.createElement('div');
    overlay.className = 'v3-wallet-history-overlay';
    overlay.innerHTML = `
      <section class="v3-wallet-history-sheet" role="dialog" aria-modal="true" aria-label="Wallet-Verlauf">
        <div class="v3-sheet-handle"></div>
        <button type="button" class="v3-sheet-close" aria-label="Schließen">×</button>
        <div class="v3-wallet-history-loading">Transaktionsverlauf wird geladen …</div>
      </section>`;
    document.body.appendChild(overlay);
    document.documentElement.style.overflow = 'hidden';
    overlay.querySelector('.v3-sheet-close')?.addEventListener('click', closeHistory);
    overlay.addEventListener('click', event => { if (event.target === overlay) closeHistory(); });

    try {
      const response = await fetch(href, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const text = await response.text();
      const parsed = new DOMParser().parseFromString(text, 'text/html');
      const history = parsed.querySelector('#wallet-history');
      if (!history) throw new Error('history_missing');
      const sheet = overlay.querySelector('.v3-wallet-history-sheet');
      sheet.querySelector('.v3-wallet-history-loading')?.remove();
      sheet.appendChild(history.cloneNode(true));
    } catch (error) {
      const loading = overlay.querySelector('.v3-wallet-history-loading');
      if (loading) {
        loading.className = 'v3-wallet-history-error';
        loading.innerHTML = '<strong>Verlauf konnte nicht geladen werden.</strong><br><small>Bitte erneut versuchen.</small>';
      }
    }
  };

  document.addEventListener('click', event => {
    const link = event.target.closest?.('.wallet-open-history');
    if (!link) return;
    event.preventDefault();
    openHistory(link.href);
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeHistory();
  });

  // A direct/fallback history URL should still become a sheet rather than
  // leaving the browser anchored in the middle of a long wallet page.
  if (location.hash === '#wallet-history') {
    const serverHistory = document.querySelector('#wallet-history');
    if (serverHistory) {
      const overlay = document.createElement('div');
      overlay.className = 'v3-wallet-history-overlay';
      overlay.innerHTML = '<section class="v3-wallet-history-sheet" role="dialog" aria-modal="true"><div class="v3-sheet-handle"></div><button type="button" class="v3-sheet-close" aria-label="Schließen">×</button></section>';
      const sheet = overlay.querySelector('.v3-wallet-history-sheet');
      sheet.appendChild(serverHistory);
      document.body.appendChild(overlay);
      document.documentElement.style.overflow = 'hidden';
      overlay.querySelector('.v3-sheet-close')?.addEventListener('click', closeHistory);
      overlay.addEventListener('click', event => { if (event.target === overlay) closeHistory(); });
      history.replaceState(null, '', location.pathname + location.search);
    }
  }
})();
