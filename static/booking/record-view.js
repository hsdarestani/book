(() => {
  const button = document.querySelector('[data-preview-zoom]');
  const stage = document.querySelector('[data-preview-stage]');
  button?.addEventListener('click', () => {
    const zoomed = stage.classList.toggle('is-zoomed');
    button.setAttribute('aria-pressed', String(zoomed));
    button.textContent = zoomed ? 'An Breite anpassen' : 'Vergrößern';
  });
  const image = document.querySelector('[data-preview-image]');
  const error = document.querySelector('[data-preview-error]');
  image?.addEventListener('error', () => {
    if (error) error.hidden = false;
  });
})();
