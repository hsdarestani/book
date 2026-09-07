(() => {
  'use strict';

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function capacitor() {
    try { return window.Capacitor || null; } catch (_) { return null; }
  }

  function platform() {
    try { return capacitor()?.getPlatform?.() || ''; } catch (_) { return ''; }
  }

  async function cameraPlugin(timeout = 1800) {
    const started = Date.now();
    do {
      try {
        const cap = capacitor();
        const plugin = cap?.Plugins?.Camera || null;
        if (plugin?.getPhoto) return plugin;
      } catch (_) {}
      await sleep(60);
    } while (Date.now() - started < timeout);
    return null;
  }

  async function ensureCameraPermission(camera) {
    if (!camera) return false;
    try {
      const current = await camera.checkPermissions?.();
      if (['granted', 'limited'].includes(String(current?.camera || '').toLowerCase())) return true;
    } catch (_) {}
    try {
      const requested = await camera.requestPermissions?.({ permissions: ['camera'] });
      const value = String(requested?.camera || '').toLowerCase();
      return ['granted', 'limited'].includes(value);
    } catch (_) {
      return false;
    }
  }

  function mimeFromFormat(format) {
    const value = String(format || '').toLowerCase();
    if (value.includes('png')) return 'image/png';
    if (value.includes('heic') || value.includes('heif')) return 'image/heic';
    return 'image/jpeg';
  }

  function extensionFromMime(type) {
    if (type.includes('png')) return 'png';
    if (type.includes('heic') || type.includes('heif')) return 'heic';
    return 'jpg';
  }

  function base64ToFile(base64, type) {
    const binary = atob(String(base64 || '').replace(/\s/g, ''));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const ext = extensionFromMime(type);
    return new File([bytes], `APlus-Patient-${Date.now()}.${ext}`, { type });
  }

  function assignFile(input, file) {
    if (!input || !file) return false;
    try {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    } catch (_) {
      return false;
    }
  }

  async function captureToInput(input, status) {
    const native = ['ios', 'android'].includes(platform());
    const camera = native ? await cameraPlugin() : null;

    if (!camera?.getPhoto) {
      // Keep the web fallback deliberately free of capture=environment. In an
      // iOS WKWebView that legacy path could terminate the app process.
      if (status && native) status.textContent = 'Native Kamera nicht verfügbar. Bitte Datei auswählen.';
      input?.click();
      return;
    }

    if (status) status.textContent = 'Kamera-Berechtigung wird geprüft …';
    const allowed = await ensureCameraPermission(camera);
    if (!allowed) {
      if (status) status.textContent = 'Kamera-Zugriff fehlt. Bitte in den iPhone-Einstellungen für A+ Esthetic erlauben.';
      return;
    }

    if (status) status.textContent = 'Kamera wird geöffnet …';
    const photo = await camera.getPhoto({
      quality: 82,
      resultType: 'base64',
      source: 'CAMERA',
      direction: 'REAR',
      correctOrientation: true,
      saveToGallery: false,
      allowEditing: false,
      width: 2048,
    });

    if (!photo?.base64String || !input) {
      if (status) status.textContent = 'Kein Foto übernommen.';
      return;
    }

    const type = mimeFromFormat(photo.format);
    const file = base64ToFile(photo.base64String, type);
    if (!assignFile(input, file)) {
      if (status) status.textContent = 'Foto aufgenommen. Bitte Datei-Auswahl einmal öffnen und erneut versuchen.';
      return;
    }
    if (status) status.textContent = `Foto bereit: ${file.name}`;
  }

  document.addEventListener('click', async event => {
    const button = event.target?.closest?.('[data-admin-native-photo]');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();

    const form = button.closest('form');
    const input = form?.querySelector('[data-patient-file]');
    const status = form?.querySelector('[data-admin-photo-status]');
    button.disabled = true;
    try {
      await captureToInput(input, status);
    } catch (error) {
      const message = String(error?.message || '').toLowerCase();
      if (status) {
        status.textContent = message.includes('cancel')
          ? 'Fotoaufnahme abgebrochen.'
          : 'Kamera konnte nicht geöffnet werden. Bitte Kamera-Berechtigung prüfen oder Datei auswählen.';
      }
    } finally {
      button.disabled = false;
    }
  }, true);
})();
