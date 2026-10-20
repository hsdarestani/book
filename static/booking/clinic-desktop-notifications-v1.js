(() => {
  'use strict';
  if (!document.querySelector('.admin-topbar') ||
      !('Notification' in window) || !window.isSecureContext) return;

  const endpoint = '/verwaltung/api/patient-form-notifications/';
  const actions = document.querySelector('.admin-topbar .admin-actions');
  if (!actions || document.querySelector('[data-clinic-notification-button]')) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'clinic-notification-button';
  button.dataset.clinicNotificationButton = '1';
  button.setAttribute('aria-label', 'Benachrichtigungen für Patientenbögen');
  actions.prepend(button);

  let cursor = 0;
  let userId = '';
  let busy = false;
  let primed = false;
  let broadcast;
  try { broadcast = new BroadcastChannel('aesthetic-clinic-forms'); } catch (_) {}

  const bell = '<svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg><span class="clinic-notification-status" aria-hidden="true"></span>';
  const updateButton = () => {
    const status = Notification.permission;
    button.innerHTML = bell;
    button.dataset.permission = status;
    button.setAttribute('aria-label', status === 'granted'
      ? 'Desktop-Benachrichtigungen aktiv'
      : status === 'denied' ? 'Benachrichtigungen im Browser blockiert'
      : 'Desktop-Benachrichtigungen aktivieren');
    button.title = status === 'granted'
      ? 'Desktop-Benachrichtigungen sind aktiv.'
      : status === 'denied'
      ? 'Bitte Benachrichtigungen in den Browser-Einstellungen erlauben.'
      : 'Desktop-Benachrichtigungen für neue Patientenbögen aktivieren';
  };

  const seenKey = id => 'aesthetic_form_notice_cursor:' + id;
  const touchKey = id => 'aesthetic_form_notice_last_poll:' + id;
  const target = patient => '/verwaltung/app/patients/?customer=' + encodeURIComponent(patient) + '#records';

  const notify = event => {
    if (Notification.permission !== 'granted') return;
    const id = String(event.customer_id || '');
    if (!/^[1-9][0-9]{0,11}$/.test(id)) return;
    try {
      const notification = new Notification(event.title, {
        body: event.body, tag: 'aesthetic-form-' + event.id,
        icon: '/static/booking/logo.png',
        renotify: false, silent: false,
      });
      notification.onclick = () => {
        notification.close();
        const url = target(id);
        const open = window.open(url, '_blank', 'noopener');
        if (!open) window.location.assign(url);
        else window.focus();
      };
    } catch (_) { /* Browser-level permissions and OS settings are authoritative. */ }
  };

  const run = async () => {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch(endpoint + '?after=' + encodeURIComponent(cursor), {
        credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'},
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.ok || !Number.isSafeInteger(Number(data.cursor))) return;
      if (!userId) {
        userId = String(data.user_id);
        const saved = Number(localStorage.getItem(seenKey(userId)) || 0);
        const last = Number(localStorage.getItem(touchKey(userId)) || 0);
        // An inactive browser session must not flood the desktop with old events.
        if (saved > 0 && Date.now() - last < 60 * 60 * 1000) {
          cursor = saved;
        } else {
          cursor = Number(data.cursor);
        }
        primed = true;
        localStorage.setItem(seenKey(userId), String(cursor));
        localStorage.setItem(touchKey(userId), String(Date.now()));
        return;
      }
      if (!primed) return;
      const previous = Math.max(cursor, Number(localStorage.getItem(seenKey(userId)) || 0));
      const events = Array.isArray(data.events) ? data.events : [];
      cursor = Math.max(previous, Number(data.cursor));
      // Advance shared cursor BEFORE showing a notification, suppressing repeats.
      localStorage.setItem(seenKey(userId), String(cursor));
      localStorage.setItem(touchKey(userId), String(Date.now()));
      broadcast?.postMessage({userId, cursor});
      for (const event of events) {
        if (Number(event.id) > previous) notify(event);
      }
    } catch (_) {
      // Temporary network failures do not affect the admin dashboard.
    } finally { busy = false; }
  };

  if (broadcast) broadcast.onmessage = event => {
    if (userId && event.data?.userId === userId) {
      cursor = Math.max(cursor, Number(event.data.cursor) || 0);
    }
  };
  button.addEventListener('click', async () => {
    if (Notification.permission === 'default') {
      try { await Notification.requestPermission(); } catch (_) {}
    }
    updateButton();
    if (Notification.permission === 'granted') void run();
  });
  updateButton();
  void run();
  // Poll only while this authorized dashboard tab is open.
  window.setInterval(() => { void run(); }, 12000);
  window.addEventListener('focus', () => { void run(); });
})();