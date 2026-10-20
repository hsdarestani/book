(() => {
  'use strict';
  // The native app can remain on book.a-esthetic.de after admin SSO.
  // Handle the form push even when app.a-esthetic.de is no longer loaded.
  const push = window.Capacitor?.Plugins?.PushNotifications;
  if (!push?.addListener) return;
  const take = event => {
    const raw = event?.notification?.data || {};
    const data = (raw.data && typeof raw.data === 'object') ? {...raw.data, ...raw} : raw;
    if (data.deeplink !== 'admin_patient') return;
    const patient = String(data.patient_customer_id || '').trim();
    if (!/^[1-9][0-9]{0,11}$/.test(patient)) return;
    // The target enforces its own admin session and record authorization.
    window.location.assign('/verwaltung/app/patients/?customer=' + encodeURIComponent(patient) + '#records');
  };
  try { push.addListener('pushNotificationActionPerformed', take); } catch (_) {}
})();