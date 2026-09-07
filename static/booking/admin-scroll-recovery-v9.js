(() => {
  'use strict';

  const isCalendar = () => window.location.pathname.includes('/verwaltung/kalender/') || window.location.pathname === '/verwaltung/';

  function recoverScroll() {
    if (isCalendar()) return;

    const root = document.documentElement;
    const body = document.body;
    if (!body) return;

    // Wallet history and modal flows can intentionally lock document scrolling.
    // If there is no visible modal/history sheet anymore, always release that lock.
    const hasOpenModal = Boolean(document.querySelector('.sb-modal.is-open, .v3-wallet-history-overlay'));
    if (!hasOpenModal) {
      root.style.removeProperty('overflow');
      root.style.removeProperty('overflow-y');
      body.style.removeProperty('overflow');
      body.style.removeProperty('overflow-y');
      body.style.removeProperty('position');
      body.style.removeProperty('height');
      body.classList.remove('sb-modal-open', 'admin-quarter-picker-open');
    }

    const drawer = document.querySelector('[data-drawer]');
    const backdrop = document.querySelector('[data-drawer-backdrop]');
    if (drawer?.getAttribute('aria-hidden') !== 'false') {
      drawer?.classList.remove('is-open');
      backdrop?.classList.remove('is-open');
    }
  }

  recoverScroll();
  document.addEventListener('DOMContentLoaded', recoverScroll, { once: true });
  window.addEventListener('pageshow', recoverScroll);
  window.addEventListener('focus', recoverScroll);

  // Android WebView can restore a page from bfcache with stale inline overflow.
  // Re-check once after all deferred admin scripts have initialized.
  setTimeout(recoverScroll, 0);
  setTimeout(recoverScroll, 250);
})();
