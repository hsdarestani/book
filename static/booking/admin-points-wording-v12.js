(() => {
  'use strict';

  const applyPointsWording = () => {
    document.querySelectorAll('.sb-drawer-nav a[href="/verwaltung/app/wallet/"]').forEach((link) => {
      link.childNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE && /A\+\s*Wallet/.test(node.textContent || '')) {
          node.textContent = (node.textContent || '').replace(/A\+\s*Wallet/g, 'A+ Punkte');
        }
      });
      link.setAttribute('aria-label', 'A+ Punkte');
    });

    if (window.location.pathname.includes('/verwaltung/app/wallet/')) {
      const title = document.querySelector('.sb-mobile-title');
      if (title) title.textContent = 'A+ Punkte';
    }
  };

  applyPointsWording();
  requestAnimationFrame(applyPointsWording);
})();
