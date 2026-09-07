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

  const setStatus = (text, mode = '') => {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('is-ok', mode === 'ok');
    status.classList.toggle('is-error', mode === 'error');
  };

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
      video.pause();
      video.srcObject = null;
    }
    if (idle) idle.hidden = false;
    if (startButton) startButton.hidden = false;
    if (stopButton) stopButton.hidden = true;
    if (!busy) setStatus('Kamera ist nicht aktiv.');
  };

  const closeScanner = () => {
    stopCamera();
    shell.hidden = true;
    document.documentElement.style.overflow = '';
  };

  const submitToken = raw => {
    const token = String(raw || '').trim();
    if (!token || busy) return;
    busy = true;
    tokenInput.value = token;
    setStatus('A+ Karte erkannt. Wallet wird geöffnet …', 'ok');
    stopCamera();
    setTimeout(() => form.requestSubmit(), 180);
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
      } catch (_) {
        // Camera frames can fail briefly while autofocus/exposure settles.
      }
    }
    raf = requestAnimationFrame(scanFrame);
  };

  const requestCamera = async () => {
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
    } catch (error) {
      if (error?.name === 'OverconstrainedError' || error?.name === 'ConstraintNotSatisfiedError') {
        return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      }
      throw error;
    }
  };

  const startCamera = async () => {
    if (stream || busy) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('Live-Kamera ist hier nicht verfügbar. Nutze „Foto scannen“ oder gib die Karten-ID ein.', 'error');
      return;
    }

    const qrDetector = await ensureDetector();
    if (!qrDetector) {
      setStatus('QR-Erkennung ist in diesem Browser nicht verfügbar. Karten-ID bitte manuell eingeben.', 'error');
      return;
    }

    try {
      stream = await requestCamera();
      video.srcObject = stream;
      await video.play();
      if (idle) idle.hidden = true;
      startButton.hidden = true;
      stopButton.hidden = false;
      setStatus('Kamera aktiv – QR-Code mittig in den Rahmen halten.');
      raf = requestAnimationFrame(scanFrame);
    } catch (error) {
      stopCamera();
      const denied = error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError';
      if (denied) {
        setStatus('Live-Kamera ist im Browser blockiert. Nutze „Foto scannen“ oder erlaube Kamera in den Website-Einstellungen.', 'error');
      } else {
        setStatus('Kamera konnte nicht gestartet werden. Nutze alternativ „Foto scannen“.', 'error');
      }
    }
  };

  const scanPhoto = async file => {
    if (!file || busy) return;
    const qrDetector = await ensureDetector();
    if (!qrDetector) {
      setStatus('QR-Erkennung ist in diesem Browser nicht verfügbar. Karten-ID bitte manuell eingeben.', 'error');
      return;
    }
    try {
      setStatus('Foto wird geprüft …');
      const bitmap = await createImageBitmap(file);
      const codes = await qrDetector.detect(bitmap);
      bitmap.close?.();
      const qr = codes.find(item => item.rawValue);
      if (!qr) {
        setStatus('Auf dem Foto wurde kein QR-Code erkannt. Bitte näher und schärfer fotografieren.', 'error');
        return;
      }
      submitToken(qr.rawValue);
    } catch (_) {
      setStatus('Das Foto konnte nicht ausgewertet werden. Bitte erneut fotografieren.', 'error');
    } finally {
      if (photoInput) photoInput.value = '';
    }
  };

  document.querySelectorAll('[data-wallet-scan-open]').forEach(button => {
    button.addEventListener('click', () => {
      busy = false;
      shell.hidden = false;
      document.documentElement.style.overflow = 'hidden';
      setStatus('Kamera ist noch nicht aktiv.');
    });
  });
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

  document.querySelectorAll('[data-wallet-amount]').forEach(button => {
    button.addEventListener('click', () => {
      const input = button.closest('.wallet-adjust-form')?.querySelector('input[name="credit_delta_eur"]');
      if (!input) return;
      input.value = button.dataset.walletAmount || '';
      input.focus();
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !shell.hidden) closeScanner();
  });
  window.addEventListener('pagehide', stopCamera);
})();
