(() => {
  'use strict';

  function initEditorModals() {
    const closeAll = () => {
      document.querySelectorAll('[data-ferrari-modal].is-open').forEach(m => {
        m.classList.remove('is-open');
        m.setAttribute('aria-hidden','true');
      });
      document.body.classList.remove('ferrari-modal-open');
    };
    document.querySelectorAll('[data-ferrari-open]').forEach(button => {
      button.addEventListener('click', () => {
        const modal = document.querySelector('[data-ferrari-modal="' + button.dataset.ferrariOpen + '"]');
        if (!modal) return;
        closeAll();
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden','false');
        document.body.classList.add('ferrari-modal-open');
        modal.querySelector('input:not([type=hidden]),textarea,button')?.focus({preventScroll:true});
      });
    });
    document.querySelectorAll('[data-ferrari-close]').forEach(button => button.addEventListener('click', closeAll));
    document.querySelectorAll('[data-ferrari-modal]').forEach(modal => modal.addEventListener('click', e => { if (e.target === modal) closeAll(); }));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });
  }

  function normalizeSheets() {
    document.querySelectorAll('.sb-sheet-head button[data-close-modal], .sb-sheet-head button[data-day-close]').forEach(button => {
      button.textContent = '‹ Zurück';
      button.setAttribute('aria-label','Zurück');
    });
  }

  function initCustomerScrollMemory() {
    const key = 'aplus-admin-customer-list-v2';
    document.querySelectorAll('[data-customer-link]').forEach(link => {
      link.addEventListener('click', () => {
        sessionStorage.setItem(key, JSON.stringify({
          y: window.scrollY,
          id: link.dataset.customerId || '',
          listUrl: location.pathname + location.search
        }));
      });
    });

    const list = document.querySelector('[data-customer-list]');
    if (list) {
      try {
        const state = JSON.parse(sessionStorage.getItem(key) || 'null');
        if (state && state.listUrl === location.pathname + location.search) {
          requestAnimationFrame(() => {
            if (Number.isFinite(Number(state.y))) window.scrollTo({top:Number(state.y),behavior:'auto'});
            const row = state.id ? document.getElementById('customer-' + state.id) : null;
            if (row) row.classList.add('is-return-target');
          });
        }
      } catch (_) {}
    }

    document.querySelectorAll('[data-customer-back]').forEach(back => {
      back.addEventListener('click', event => {
        try {
          const state = JSON.parse(sessionStorage.getItem(key) || 'null');
          if (state && document.referrer && new URL(document.referrer).pathname.includes('/verwaltung/app/patients/')) {
            event.preventDefault();
            history.back();
          }
        } catch (_) {}
      });
    });
  }

  function initStickyCalendarDates() {
    const shell = document.querySelector('.sb-calendar-shell');
    const days = shell?.querySelector('.sb-calendar-days');
    const heads = days ? [...days.querySelectorAll('.sb-day-head')] : [];
    if (!shell || !days || !heads.length) return;

    const sticky = document.createElement('div');
    sticky.className = 'ferrari-calendar-sticky';
    sticky.innerHTML = '<div class="ferrari-calendar-sticky-inner"><div class="ferrari-sticky-axis"></div><div class="ferrari-sticky-days"></div></div>';
    const target = sticky.querySelector('.ferrari-sticky-days');
    target.style.setProperty('--day-count', String(heads.length));
    target.innerHTML = heads.map(h => '<div class="ferrari-sticky-day">' + h.innerHTML + '</div>').join('');
    document.body.appendChild(sticky);

    const sync = () => {
      const rect = shell.getBoundingClientRect();
      const top = window.innerWidth <= 760 ? 52 + (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sat')) || 0) : 88;
      sticky.classList.toggle('is-visible', rect.top < top && rect.bottom > top + 60);
      const bodyDays = shell.querySelector('.sb-calendar-days');
      if (bodyDays) {
        target.style.width = bodyDays.scrollWidth + 'px';
        const scrollLeft = shell.scrollLeft || 0;
        target.style.transform = 'translateX(' + (-scrollLeft) + 'px)';
      }
    };
    shell.addEventListener('scroll', sync, {passive:true});
    window.addEventListener('scroll', sync, {passive:true});
    window.addEventListener('resize', sync);
    sync();
  }

  function initReturnHighlight() {
    document.querySelectorAll('.is-return-target').forEach(row => setTimeout(() => row.classList.remove('is-return-target'), 1400));
  }

  function init() {
    normalizeSheets();
    initEditorModals();
    initCustomerScrollMemory();
    initStickyCalendarDates();
    initReturnHighlight();
    new MutationObserver(normalizeSheets).observe(document.body,{childList:true,subtree:true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
})();