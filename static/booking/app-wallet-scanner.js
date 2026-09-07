(() => {
  'use strict';

  const shell = document.querySelector('[data-wallet-scanner]');
  if (!shell) return;

  const video = shell.querySelector('[data-wallet-camera]');
  const idle = shell.querySelector('[data-wallet-camera-idle]');
  const status = shell.querySelector('[data-wallet-scan-status]');
  const startButton = shell.querySelector('[data-wallet-camera-start]');
  const stopButton = shell.querySelector('[data-wallet-camera-stop]');
  const photoButton = shell.querySelector('[data-wallet-photo-start]');
  const photoInput = shell.querySelector('[data-wallet-photo-input]');
  const form = shell.querySelector('[data-wallet-scan-form]');
  const tokenInput = shell.querySelector('[data-wallet-token]');

  let stream = null;
  let detector = null;
  let raf = 0;
  let busy = false;
  let nativeScanning = false;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const setStatus = (text, mode = '') => {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('is-ok', mode === 'ok');
    status.classList.toggle('is-error', mode === 'error');
  };

  const cap = () => {
    try { return window.Capacitor || null; } catch (_) { return null; }
  };
  const nativePlatform = () => {
    try { return cap()?.getPlatform?.() || ''; } catch (_) { return ''; }
  };
  const plugin = name => {
    try { return cap()?.Plugins?.[name] || null; } catch (_) { return null; }
  };

  async function waitForPlugin(name, method, timeout = 2200) {
    const started = Date.now();
    do {
      const item = plugin(name);
      if (item && typeof item[method] === 'function') return item;
      await sleep(70);
    } while (Date.now() - started < timeout);
    return null;
  }

  async function ensureNativeCameraPermission() {
    const camera = await waitForPlugin('Camera', 'requestPermissions', 900);
    if (!camera) return true; // scanner itself will request if Camera plugin is unavailable
    try {
      const current = await camera.checkPermissions?.();
      if (['granted', 'limited'].includes(String(current?.camera || '').toLowerCase())) return true;
    } catch (_) {}
    try {
      const requested = await camera.requestPermissions({ permissions: ['camera'] });
      return ['granted', 'limited'].includes(String(requested?.camera || '').toLowerCase());
    } catch (_) {
      return false;
    }
  }

  const ensureDetector = async () => {
    if (detector) return detector;
    if (!('BarcodeDetector' in window)) return null;
    try {
      const formats = typeof BarcodeDetector.getSupportedFormats === 'function'
        ? await BarcodeDetector.getSupportedFormats()
        : ['qr_code'];
      if (!formats.includes('qr_code')) return null;
      detector = new BarcodeDetector({ formats: ['qr_code'] });
      return detector;
    } catch (_) {
      detector = null;
      return null;
    }
  };

  const stopCamera = () => {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    if (stream) stream.getTracks().forEach(track => track.stop());
    stream = null;
    if (video) {
      try { video.pause(); } catch (_) {}
      video.srcObject = null;
    }
    if (idle) idle.hidden = false;
    if (startButton) startButton.hidden = false;
    if (stopButton) stopButton.hidden = true;
    if (!busy && !nativeScanning) setStatus('Kamera ist nicht aktiv.');
  };

  const closeScanner = () => {
    stopCamera();
    shell.hidden = true;
    document.documentElement.style.overflow = '';
    document.body.style.overflow = '';
  };

  const submitToken = raw => {
    const token = String(raw || '').trim();
    if (!token || busy) return;
    busy = true;
    tokenInput.value = token;
    setStatus('A+ Karte erkannt. Patientenprofil wird geöffnet …', 'ok');
    stopCamera();
    setTimeout(() => form.requestSubmit(), 120);
  };

  const scanFrame = async () => {
    if (!stream || !detector || busy) return;
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      try {
        const codes = await detector.detect(video);
        const qr = codes.find(item => item.rawValue);
        if (qr) {
          submitToken(qr.rawValue);
          return;
        }
      } catch (_) {}
    }
    raf = requestAnimationFrame(scanFrame);
  };

  const requestCamera = async () => {
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
    } catch (error) {
      if (['OverconstrainedError', 'ConstraintNotSatisfiedError'].includes(error?.name)) {
        return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      }
      throw error;
    }
  };

  async function startNative() {
    const platform = nativePlatform();
    if (!['ios', 'android'].includes(platform)) return false;

    nativeScanning = true;
    if (startButton) startButton.disabled = true;
    setStatus(platform === 'ios' ? 'iPhone-Kamera wird vorbereitet …' : 'Native Kamera wird vorbereitet …');

    try {
      const allowed = await ensureNativeCameraPermission();
      if (!allowed) {
        setStatus('Kamera-Zugriff fehlt. Bitte in den Geräte-Einstellungen für A+ Esthetic erlauben.', 'error');
        return true;
      }

      const scanner = await waitForPlugin('CapacitorBarcodeScanner', 'scanBarcode');
      if (!scanner) {
        // Returning false lets the WebKit camera fallback run if the native bridge
        // is unexpectedly unavailable on a remote Book page.
        setStatus('Native QR-Kamera wird nicht erkannt – Web-Kamera wird versucht.');
        return false;
      }

      setStatus('Kamera aktiv – A+ QR-Code mittig halten.');
      const result = await scanner.scanBarcode({
        hint: 0,
        cameraDirection: 1,
        scanOrientation: 3,
        scanInstructions: 'A+ QR-Code mittig in den Rahmen halten',
        scanButton: false,
        scanText: 'Scannen',
      });
      const value = String(
        result?.ScanResult || result?.scanResult || result?.value || result?.content || ''
      ).trim();
      if (value) submitToken(value);
      else setStatus('Kein QR-Code erkannt. Bitte erneut versuchen.', 'error');
      return true;
    } catch (error) {
      const text = String(error?.message || error || '').toLowerCase();
      if (text.includes('cancel')) setStatus('Scan abgebrochen.');
      else if (text.includes('permission') || text.includes('denied')) {
        setStatus('Kamera-Berechtigung fehlt. Bitte in den iPhone-Einstellungen freigeben.', 'error');
      } else {
        setStatus('Native Kamera konnte nicht geöffnet werden. Web-Kamera wird versucht.', 'error');
        return false;
      }
      return true;
    } finally {
      nativeScanning = false;
      if (startButton) startButton.disabled = false;
    }
  }

  const startCamera = async () => {
    if (stream || busy || nativeScanning) return;
    const handledNative = await startNative();
    if (handledNative) return;

    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('Kamera ist hier nicht verfügbar. Karten-ID bitte manuell eingeben.', 'error');
      return;
    }
    const qrDetector = await ensureDetector();
    if (!qrDetector) {
      setStatus('QR-Erkennung ist in dieser WebView nicht verfügbar. Bitte App-Kamera-Berechtigung prüfen oder Karten-ID eingeben.', 'error');
      return;
    }
    try {
      stream = await requestCamera();
      video.srcObject = stream;
      await video.play();
      if (idle) idle.hidden = true;
      if (startButton) startButton.hidden = true;
      if (stopButton) stopButton.hidden = false;
      setStatus('Kamera aktiv – QR-Code mittig in den Rahmen halten.');
      raf = requestAnimationFrame(scanFrame);
    } catch (error) {
      stopCamera();
      const denied = ['NotAllowedError', 'PermissionDeniedError'].includes(error?.name);
      setStatus(
        denied
          ? 'Kamera-Berechtigung fehlt. Bitte in den Einstellungen für A+ Esthetic freigeben.'
          : 'Kamera konnte nicht gestartet werden.',
        'error'
      );
    }
  };

  const scanPhoto = async file => {
    if (!file || busy) return;
    const qrDetector = await ensureDetector();
    if (!qrDetector) {
      setStatus('Foto-QR-Erkennung ist hier nicht verfügbar. Bitte native Kamera oder Karten-ID verwenden.', 'error');
      return;
    }
    try {
      setStatus('Foto wird geprüft …');
      const bitmap = await createImageBitmap(file);
      const codes = await qrDetector.detect(bitmap);
      bitmap.close?.();
      const qr = codes.find(item => item.rawValue);
      if (!qr) {
        setStatus('Kein QR-Code erkannt.', 'error');
        return;
      }
      submitToken(qr.rawValue);
    } catch (_) {
      setStatus('Foto konnte nicht ausgewertet werden.', 'error');
    } finally {
      if (photoInput) photoInput.value = '';
    }
  };

  document.querySelectorAll('[data-wallet-scan-open]').forEach(button => button.addEventListener('click', () => {
    busy = false;
    shell.hidden = false;
    document.documentElement.style.overflow = 'hidden';
    document.body.style.overflow = 'hidden';
    setStatus('Kamera ist noch nicht aktiv.');
  }));
  shell.querySelectorAll('[data-wallet-scan-close]').forEach(button => button.addEventListener('click', closeScanner));
  shell.addEventListener('click', event => { if (event.target === shell) closeScanner(); });
  startButton?.addEventListener('click', startCamera);
  stopButton?.addEventListener('click', stopCamera);
  photoButton?.addEventListener('click', () => photoInput?.click());
  photoInput?.addEventListener('change', () => scanPhoto(photoInput.files?.[0]));

  form.addEventListener('submit', event => {
    if (!tokenInput.value.trim()) {
      event.preventDefault();
      setStatus('Bitte zuerst QR-Code scannen oder Karten-ID eingeben.', 'error');
    } else {
      busy = true;
      stopCamera();
    }
  });

  document.querySelectorAll('[data-wallet-amount]').forEach(button => button.addEventListener('click', () => {
    const input = button.closest('.points-adjust-form,.point-adjust-form')?.querySelector('input[name="point_delta"]');
    if (input) {
      input.value = button.dataset.walletAmount || '';
      input.focus();
    }
  }));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !shell.hidden) closeScanner(); });
  window.addEventListener('pagehide', stopCamera);
})();
