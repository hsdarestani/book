(() => {
  'use strict';
  const MAX_IMAGE_BYTES = 900 * 1024;
  let overlay;
  function waitLayer() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'aplus-wait-layer';
    overlay.hidden = true;
    overlay.innerHTML = '<div class="aplus-wait-card" role="status" aria-live="polite"><span class="aplus-wait-mark">A+</span><span class="aplus-wait-spinner"></span><strong data-wait-title>Bitte warten …</strong><small data-wait-note>Ihre Änderung wird sicher gespeichert.</small></div>';
    document.body.appendChild(overlay);
    return overlay;
  }
  function showWait(title, note) {
    const layer = waitLayer();
    layer.querySelector('[data-wait-title]').textContent = title || 'Bitte warten …';
    layer.querySelector('[data-wait-note]').textContent = note || 'Ihre Änderung wird sicher gespeichert.';
    layer.hidden = false;
    document.documentElement.classList.add('aplus-is-waiting');
  }
  function hideWait() {
    if (overlay) overlay.hidden = true;
    document.documentElement.classList.remove('aplus-is-waiting');
  }
  async function compressImage(file) {
    if (!file || !file.type.startsWith('image/') || file.size <= MAX_IMAGE_BYTES || /heic|heif/i.test(file.type)) return file;
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1800 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    let quality = .86, blob;
    do {
      blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
      quality -= .08;
    } while (blob && blob.size > MAX_IMAGE_BYTES && quality >= .5);
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' }) : file;
  }
  function assign(input, file) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  }
  document.addEventListener('change', async event => {
    const input = event.target.closest?.('[data-patient-file]');
    const file = input?.files?.[0];
    if (!input || !file) return;
    const status = input.closest('form')?.querySelector('[data-admin-photo-status]');
    if (status) status.textContent = 'Datei wird vorbereitet …';
    try {
      const ready = await compressImage(file);
      if (ready !== file) assign(input, ready);
      if (status) status.textContent = `Bereit: ${ready.name} · ${Math.ceil(ready.size / 1024)} KB`;
    } catch (_) {
      if (status) status.textContent = `Bereit: ${file.name}`;
    }
  }, true);
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (button) {
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    }
    const isUpload = form.matches('.app-patient-upload');
    showWait(isUpload ? 'Datei wird hochgeladen …' : 'Änderung wird gespeichert …', isUpload ? 'Bitte diese Seite geöffnet lassen.' : 'Einen kurzen Moment bitte.');
    setTimeout(() => {
      if (document.visibilityState === 'visible') {
        hideWait();
        if (button) {
          button.disabled = false;
          button.removeAttribute('aria-busy');
        }
      }
    }, 45000);
  }, true);
  window.addEventListener('pageshow', hideWait);
})();