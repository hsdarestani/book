(() => {
  'use strict';

  const shell = document.querySelector('[data-wallet-scanner]');
  if (!shell) return;

  const video = shell.querySelector('[data-wallet-camera]');
  const stage = shell.querySelector('[data-wallet-camera-stage]');
  const idle = shell.querySelector('[data-wallet-camera-idle]');
  const status = shell.querySelector('[data-wallet-scan-status]');
  const startButton = shell.querySelector('[data-wallet-camera-start]');
  const stopButton = shell.querySelector('[data-wallet-camera-stop]');
  const form = shell.querySelector('[data-wallet-scan-form]');
  const tokenInput = shell.querySelector('[data-wallet-token]');
  let stream = null;
  let detector = null;
  let raf = 0;
  let busy = false;

  const setStatus = (text, mode = '') => {
    status.textContent = text;
    status.classList.toggle('is-ok', mode === 'ok');
    status.classList.toggle('is-error', mode === 'error');
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
    idle.hidden = false;
    startButton.hidden = false;
    stopButton.hidden = true;
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
        // Transient detector errors are expected while the camera is warming up.
      }
    }
    raf = requestAnimationFrame(scanFrame);
  };

  const startCamera = async () => {
    if (stream || busy) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('Dieser Browser erlaubt keinen Kamerazugriff. Karten-ID bitte manuell eingeben.', 'error');
      return;
    }

    let supportsQr = false;
    if ('BarcodeDetector' in window) {
      try {
        const formats = typeof BarcodeDetector.getSupportedFormats === 'function'
          ? await BarcodeDetector.getSupportedFormats()
          : ['qr_code'];
        supportsQr = formats.includes('qr_code');
        if (supportsQr) detector = new BarcodeDetector({ formats: ['qr_code'] });
      } catch (_) {
        detector = null;
      }
    }
    if (!supportsQr || !detector) {
      setStatus('QR-Erkennung ist in diesem Browser nicht verfügbar. Nutze Chrome oder gib die Karten-ID manuell ein.', 'error');
      return;
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      video.srcObject = stream;
      await video.play();
      idle.hidden = true;
      startButton.hidden = true;
      stopButton.hidden = false;
      setStatus('Kamera aktiv – QR-Code mittig in den Rahmen halten.');
      raf = requestAnimationFrame(scanFrame);
    } catch (error) {
      stopCamera();
      const denied = error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError';
      setStatus(
        denied ? 'Kamerazugriff wurde nicht erlaubt. Bitte Browser-Berechtigung prüfen.' : 'Kamera konnte nicht gestartet werden.',
        'error',
      );
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
  startButton.addEventListener('click', startCamera);
  stopButton.addEventListener('click', stopCamera);
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
