(() => {
  'use strict';

  const init = () => {
    if (!document.body?.classList.contains('patient-file-body')) return;

    const drawer = document.querySelector('[data-drawer]');
    const backdrop = document.querySelector('[data-drawer-backdrop]');
    const openers = [...document.querySelectorAll('[data-drawer-open]')];
    if (!drawer || !openers.length) return;

    const setOpen = open => {
      drawer.classList.toggle('is-open', open);
      backdrop?.classList.toggle('is-open', open);
      drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
      document.body.classList.toggle('patient-drawer-open', open);
    };

    openers.forEach(button => {
      if (button.dataset.patientDrawerBound === '1') return;
      button.dataset.patientDrawerBound = '1';
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        setOpen(true);
      });
    });

    if (backdrop && backdrop.dataset.patientDrawerBound !== '1') {
      backdrop.dataset.patientDrawerBound = '1';
      backdrop.addEventListener('click', () => setOpen(false));
    }

    drawer.querySelectorAll('a').forEach(link => {
      if (link.dataset.patientDrawerBound === '1') return;
      link.dataset.patientDrawerBound = '1';
      link.addEventListener('click', () => setOpen(false));
    });

    if (document.documentElement.dataset.patientDrawerEscape !== '1') {
      document.documentElement.dataset.patientDrawerEscape = '1';
      document.addEventListener('keydown', event => {
        if (event.key === 'Escape') setOpen(false);
      });
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
