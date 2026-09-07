(() => {
  'use strict';

  function cameraPlugin() {
    try { return window.Capacitor?.Plugins?.Camera || null; } catch (_) { return null; }
  }

  async function captureToInput(input, status) {
    const camera = cameraPlugin();
    if (!camera?.getPhoto) {
      // Browser fallback deliberately avoids capture=environment on iOS WKWebView,
      // which was the path that could terminate the app.
      input?.click();
      return;
    }
    if (status) status.textContent = 'Kamera wird geöffnet …';
    const photo = await camera.getPhoto({
      quality: 90,
      resultType: 'uri',
      source: 'CAMERA',
      direction: 'REAR',
      correctOrientation: true,
      presentationStyle: 'fullscreen',
    });
    if (!photo?.webPath || !input) return;
    const response = await fetch(photo.webPath);
    const blob = await response.blob();
    const type = blob.type || 'image/jpeg';
    const ext = type.includes('png') ? 'png' : 'jpg';
    const file = new File([blob], `APlus-Patient-${Date.now()}.${ext}`, { type });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    if (status) status.textContent = `Foto bereit: ${file.name}`;
  }

  document.addEventListener('click', async event => {
    const button = event.target?.closest?.('[data-admin-native-photo]');
    if (!button) return;
    event.preventDefault();
    const form = button.closest('form');
    const input = form?.querySelector('[data-patient-file]');
    const status = form?.querySelector('[data-admin-photo-status]');
    button.disabled = true;
    try {
      await captureToInput(input, status);
    } catch (error) {
      if (status) status.textContent = 'Kamera konnte nicht geöffnet werden. Bitte Datei auswählen.';
    } finally {
      button.disabled = false;
    }
  }, true);
})();
