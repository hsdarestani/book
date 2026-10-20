(() => {
  'use strict';
  if (document.documentElement.dataset.adminPage !== 'patients') return;
  const nav = document.querySelector('.customer-profile-tabs');
  const controls = document.querySelector('[data-customer-control-grid]');
  if (!nav || !controls) return;

  const buttons = [...nav.querySelectorAll('button[data-customer-tab]')];
  const panels = [...document.querySelectorAll('[data-customer-panel]')];
  const valid = new Set(['overview', 'appointments', 'records', 'points']);
  const profile = controls.querySelector('.patient-profile-panel');
  const pointForm = controls.querySelector('.patient-points-panel');
  nav.setAttribute('role', 'tablist');

  const requestedTab = () => {
    const raw = decodeURIComponent((location.hash || '').replace(/^#/, ''));
    return valid.has(raw) ? raw : 'overview';
  };

  function showTab(raw, updateUrl = false) {
    const tab = valid.has(raw) ? raw : 'overview';
    for (const panel of panels) {
      const active = panel.dataset.customerPanel === tab;
      panel.hidden = !active;
      panel.classList.toggle('is-tab-hidden', !active);
      panel.setAttribute('aria-hidden', active ? 'false' : 'true');
    }

    const openControls = tab === 'overview' || tab === 'points';
    controls.hidden = !openControls;
    controls.classList.toggle('is-tab-hidden', !openControls);
    controls.setAttribute('aria-hidden', openControls ? 'false' : 'true');
    controls.classList.toggle('is-single-panel', true);
    for (const [panel, visible] of [[profile, tab === 'overview'], [pointForm, tab === 'points']]) {
      if (!panel) continue;
      panel.hidden = !visible;
      panel.classList.toggle('is-tab-hidden', !visible);
      panel.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }

    buttons.forEach(btn => {
      const selected = btn.dataset.customerTab === tab;
      btn.classList.toggle('is-active', selected);
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
      btn.setAttribute('role', 'tab');
      btn.tabIndex = selected ? 0 : -1;
    });

    if (updateUrl) {
      const hash = tab === 'overview' ? '' : '#' + tab;
      history.replaceState(null, '', location.pathname + location.search + hash);
    }
  }

  nav.addEventListener('click', event => {
    const button = event.target.closest('button[data-customer-tab]');
    if (!button || !nav.contains(button)) return;
    showTab(button.dataset.customerTab, true);
  });
  nav.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const active = Math.max(0, buttons.findIndex(button => button.getAttribute('aria-selected') === 'true'));
    const next = event.key === 'Home' ? 0 :
      event.key === 'End' ? buttons.length - 1 :
      (active + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
    showTab(buttons[next].dataset.customerTab, true);
  });
  window.addEventListener('hashchange', () => showTab(requestedTab()));
  window.addEventListener('popstate', () => showTab(requestedTab()));

  // Run even when CSS is still being cached. Never reveal unrelated sections.
  showTab(requestedTab());
})();
