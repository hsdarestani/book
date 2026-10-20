/* Public web booking only. Never interrupt the A+ Esthetic native app. */
(() => {
  'use strict';
  const overlay = document.getElementById('club-app-invite');
  if (!overlay) return;

  const DISMISS_KEY = 'aesthetic-club-invite-dismissed-v1';
  const WEEK = 7 * 24 * 60 * 60 * 1000;

  function isPublicBrowser() {
    // The club promotion belongs to this URL only, not the app or another host.
    if (window.location.hostname.toLowerCase() !== 'book.a-esthetic.de') return false;
    if (window.self !== window.top) return false; // No embedded booking in an app.
    const params = new URLSearchParams(window.location.search);
    if (params.get('hide_club_invite') === '1' || params.get('in_app') === '1') return false;
    if (['app', 'native', 'webview', 'capacitor'].includes((params.get('source') || '').toLowerCase())) return false;
    if (['app', 'native'].includes((params.get('utm_source') || '').toLowerCase())) return false;
    if (navigator.standalone === true) return false;
    if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return false;
    if (window.Capacitor || window.cordova || window.ReactNativeWebView || window.Android) return false;
    if (window.webkit && window.webkit.messageHandlers &&
        (window.webkit.messageHandlers.cordova || window.webkit.messageHandlers.capacitor)) return false;

    const agent = navigator.userAgent || '';
    if (/; wv\)|\bA\+\s*Esthetic\s*App\b|\bCapacitor\b|\bAndroidWebView\b/i.test(agent)) return false;
    // iOS WKWebView normally lacks a browser token; Safari/Chrome/Firefox iOS have one.
    if (/iPad|iPhone|iPod/i.test(agent) && !/Safari|CriOS|FxiOS|EdgiOS|OPiOS/i.test(agent)) return false;
    return true;
  }

  if (!isPublicBrowser()) return;
  try {
    if (Number(window.localStorage.getItem(DISMISS_KEY)) > Date.now()) return;
  } catch (_) { /* Browsing without storage still works. */ }

  const dialog = overlay.querySelector('[role="dialog"]');
  const closeButton = overlay.querySelector('.club-invite__close');
  let previousFocus = null;

  function rememberDismissal() {
    try { window.localStorage.setItem(DISMISS_KEY, String(Date.now() + WEEK)); } catch (_) {}
  }

  function close() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('club-invite-open');
    document.removeEventListener('keydown', onKeydown);
    rememberDismissal();
    if (previousFocus && previousFocus.isConnected) previousFocus.focus({ preventScroll: true });
  }

  function onKeydown(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const focusable = [...dialog.querySelectorAll('button:not([disabled]),a[href]')];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  overlay.querySelectorAll('[data-club-dismiss], [data-club-download]').forEach(el => el.addEventListener('click', close));
  overlay.addEventListener('click', event => { if (event.target === overlay) close(); });

  // Allow the booking page to become usable before showing the invitation.
  window.setTimeout(() => {
    if (document.visibilityState === 'hidden' || !isPublicBrowser()) return;
    previousFocus = document.activeElement;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('club-invite-open');
    document.addEventListener('keydown', onKeydown);
    closeButton.focus({ preventScroll: true });
  }, 1100);
})();
