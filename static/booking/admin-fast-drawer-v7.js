(() => {
  'use strict';

  const getParts = () => ({
    drawer: document.querySelector('[data-drawer]'),
    backdrop: document.querySelector('[data-drawer-backdrop]'),
  });

  const setOpen = open => {
    const { drawer, backdrop } = getParts();
    if (!drawer) return;
    drawer.classList.toggle('is-open', open);
    drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
    backdrop?.classList.toggle('is-open', open);
  };

  // Capture phase intentionally wins over older per-button handlers so opening
  // the drawer does not run duplicate animation/state code on slower WebViews.
  document.addEventListener('click', event => {
    const opener = event.target.closest?.('[data-drawer-open]');
    if (opener) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(true);
      return;
    }

    const backdrop = event.target.closest?.('[data-drawer-backdrop]');
    if (backdrop) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setOpen(false);
      return;
    }

    const drawerLink = event.target.closest?.('[data-drawer] a');
    if (drawerLink) setOpen(false);
  }, true);

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setOpen(false);
  }, true);
})();
