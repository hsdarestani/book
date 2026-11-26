(() => {
  'use strict';
  const adminHeader = document.querySelector('[data-clinic-header]');
  if (!adminHeader || adminHeader.dataset.clinicViewOnly === '1') return;

  const endpoint = '/verwaltung/api/patient-form-notifications/';
  const inbox = '/verwaltung/api/notifications/';
  const desktopAvailable = 'Notification' in window && window.isSecureContext;
  const actions = adminHeader.querySelector('.admin-actions');
  if (!actions || document.querySelector('[data-clinic-notification-button]')) return;

  const bell = '<svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>';
  function makeButton(mobile = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = mobile ? 'sb-icon-button clinic-notification-button' : 'clinic-notification-button';
    button.dataset.clinicNotificationButton = '1';
    button.setAttribute('aria-label', 'Benachrichtigungen');
    button.setAttribute('aria-controls', 'clinic-notification-inbox');
    button.setAttribute('aria-expanded', 'false');
    button.innerHTML = bell + '<span class="clinic-inbox-count" aria-hidden="true" hidden></span>';
    return button;
  }

  const buttons = [makeButton()];
  actions.prepend(buttons[0]);
  const mobileBar = document.querySelector('.sb-reference-calendar-bar');
  if (mobileBar) {
    const button = makeButton(true);
    mobileBar.append(button);
    buttons.push(button);
  }
  const panel = document.createElement('section');
  panel.id = 'clinic-notification-inbox';
  panel.className = 'clinic-notification-inbox';
  panel.hidden = true;
  panel.setAttribute('aria-labelledby', 'clinic-notification-heading');
  panel.innerHTML = `<header><h2 id="clinic-notification-heading">Benachrichtigungen</h2>
    <button type="button" data-inbox-close aria-label="Benachrichtigungen schließen">×</button></header>
    <p data-inbox-status role="status"></p><ul data-inbox-list></ul>
    <button type="button" data-inbox-desktop hidden>Desktop-Hinweise aktivieren</button>`;
  document.body.append(panel);
  const close = panel.querySelector('[data-inbox-close]');
  const status = panel.querySelector('[data-inbox-status]');
  const list = panel.querySelector('[data-inbox-list]');
  const optIn = panel.querySelector('[data-inbox-desktop]');
  const dateFormat = new Intl.DateTimeFormat('de-DE', {dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Berlin'});
  let trigger;
  let csrfToken;
  let inboxLoaded = false;
  let inboxRefresh;
  let marking = false;
  let snapshot;

  const closeInbox = (focus = true) => {
    panel.hidden = true;
    for (const button of buttons) button.setAttribute('aria-expanded', 'false');
    if (focus) trigger?.focus();
  };
  const positionInbox = () => {
    if (!panel.hidden && trigger) {
      panel.style.top = Math.min(trigger.getBoundingClientRect().bottom + 8, 140) + 'px';
    }
  };

  async function inboxRequest(options) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(inbox, {
        cache: 'no-store', credentials: 'same-origin', ...options, signal: controller.signal,
      });
      if (!response.ok || response.redirected) throw new Error('Inbox unavailable');
      const data = await response.json();
      if (!data.ok) throw new Error('Inbox unavailable');
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function markRead(event) {
    if (marking) return false;
    marking = true;
    try {
      await inboxRefresh;
      await inboxRequest({method: 'POST', body: new URLSearchParams({record: event.id}),
        headers: {'X-CSRFToken': csrfToken}});
      return true;
    } catch (_) {
      status.textContent = 'Der Lesestatus konnte nicht gespeichert werden.';
      return false;
    } finally {
      marking = false;
    }
  }

  function eventItem(event) {
    const item = document.createElement('li');
    const content = document.createElement('div');
    const link = document.createElement('a');
    if (!/^\/verwaltung\/patienten\/\d+\/datei\/[a-f0-9-]{36}\/ansicht\/$/.test(event.url)) return item;
    link.href = event.url;
    link.textContent = event.title;
    if (!event.read) {
      item.classList.add('is-unread');
      link.addEventListener('click', async click => {
        if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return;
        click.preventDefault();
        if (await markRead(event)) window.location.assign(link.href);
      });
    }
    const time = document.createElement('time');
    time.dateTime = event.created_at;
    time.textContent = dateFormat.format(new Date(event.created_at));
    content.append(link, time);
    item.append(content);
    if (!event.read) {
      const mark = document.createElement('button');
      mark.type = 'button';
      mark.textContent = 'Als gelesen markieren';
      mark.addEventListener('click', async () => {
        mark.disabled = true;
        if (await markRead(event)) {
          await refreshInbox();
          close.focus();
        }
        mark.disabled = false;
      });
      item.append(mark);
    }
    return item;
  }

  function refreshInbox() {
    if (marking || document.visibilityState !== 'visible') return;
    if (!inboxRefresh) inboxRefresh = loadInbox().finally(() => { inboxRefresh = null; });
    return inboxRefresh;
  }

  async function loadInbox() {
    if (!inboxLoaded) status.textContent = 'Benachrichtigungen werden geladen …';
    try {
      const data = await inboxRequest({headers: {Accept: 'application/json'}});
      csrfToken = data.csrf_token;
      inboxLoaded = true;
      const count = Number(data.unread);
      for (const button of buttons) {
        const badge = button.querySelector('.clinic-inbox-count');
        badge.hidden = !count;
        badge.textContent = count > 99 ? '99+' : String(count);
        button.setAttribute('aria-label', count ? `Benachrichtigungen (${count} ungelesen)` : 'Benachrichtigungen');
      }
      const next = JSON.stringify(data.events);
      if (snapshot !== next) {
        snapshot = next;
        list.replaceChildren(...data.events.map(eventItem));
      }
      status.textContent = data.events.length ? `${count} ungelesen · letzte 30 Tage` : 'Keine Benachrichtigungen vorhanden.';
    } catch (_) {
      status.textContent = 'Benachrichtigungen konnten nicht geladen werden. Bitte erneut öffnen.';
    }
  }

  for (const button of buttons) {
    button.addEventListener('click', () => {
      if (!panel.hidden) return closeInbox();
      trigger = button;
      panel.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      positionInbox();
      close.focus();
      void refreshInbox();
    });
  }
  close.addEventListener('click', () => closeInbox());
  document.addEventListener('pointerdown', event => {
    if (!panel.hidden && !panel.contains(event.target) && !buttons.some(button => button.contains(event.target))) {
      closeInbox(false);
    }
  });
  document.addEventListener('keydown', event => {
    if (!panel.hidden && event.key === 'Escape') closeInbox();
  });
  window.addEventListener('resize', positionInbox);

  let cursor = 0;
  let userId = '';
  let busy = false;
  let primed = false;
  let broadcast;
  try { broadcast = new BroadcastChannel('aesthetic-clinic-forms'); } catch (_) {}

  const seenKey = id => 'aesthetic_form_notice_cursor:' + id;
  const touchKey = id => 'aesthetic_form_notice_last_poll:' + id;
  const target = patient => '/verwaltung/app/patients/?customer=' + encodeURIComponent(patient) + '#records';

  const notify = event => {
    if (!desktopAvailable || Notification.permission !== 'granted') return;
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
    if (!desktopAvailable || Notification.permission !== 'granted' || busy) return;
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
  const updateDesktopControl = () => {
    optIn.hidden = !desktopAvailable || Notification.permission === 'granted';
    if (desktopAvailable) optIn.disabled = Notification.permission === 'denied';
    optIn.textContent = optIn.disabled
      ? 'Desktop-Hinweise im Browser blockiert' : 'Desktop-Hinweise aktivieren';
  };
  optIn.addEventListener('click', async () => {
    try { await Notification.requestPermission(); } catch (_) {}
    updateDesktopControl();
    void run();
  });
  updateDesktopControl();
  const poll = () => {
    void run();
    void refreshInbox();
  };
  poll();
  window.setInterval(poll, 12000);
  window.addEventListener('focus', poll);
})();
