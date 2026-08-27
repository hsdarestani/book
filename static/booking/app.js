(() => {
  const state = {
    service: null,
    staff: null,
    startsAt: null,
    slotLabel: null,
    dateLabel: null,
    currentStep: 1,
    maxStep: 1,
  };

  const providerPhotos = {
    'Frau Ariane Regaei': '/static/booking/staff/ariane-regaei.jpg',
    'Qamar Hameed': '/static/booking/staff/doctor-male.jpg',
  };
  const providerTitles = {
    'Frau Ariane Regaei': { badge: 'Ärztin', title: 'Ärztin für ästhetische Medizin' },
    'Qamar Hameed': { badge: 'Arzt', title: 'Arzt für ästhetische Medizin' },
  };

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const errorBox = $('#booking-error');

  function showError(message) {
    errorBox.textContent = message || 'Es ist ein Fehler aufgetreten. Bitte versuche es erneut.';
    errorBox.hidden = false;
    errorBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = '';
  }
  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }
  function canGo(step) {
    if (step === 1) return true;
    if (step === 2) return Boolean(state.service);
    if (step === 3) return Boolean(state.service && state.staff);
    if (step === 4) return Boolean(state.service && state.staff && state.startsAt);
    if (step === 5) return true;
    return false;
  }
  function updateProgress(step) {
    $$('.progress-dot').forEach((dot) => {
      const n = Number(dot.dataset.progress);
      dot.classList.toggle('is-active', n === Math.min(step, 4));
      dot.classList.toggle('is-done', step > n || step === 5);
      dot.classList.toggle('is-available', canGo(n));
      dot.disabled = !canGo(n);
      dot.setAttribute('aria-current', n === Math.min(step, 4) ? 'step' : 'false');
    });
  }
  function go(step) {
    if (step <= 4 && !canGo(step)) return;
    clearError();
    state.currentStep = step;
    state.maxStep = Math.max(state.maxStep, Math.min(step, 4));
    $$('.step').forEach((x) => x.classList.toggle('is-active', Number(x.dataset.step) === step));
    updateProgress(step);
    window.scrollTo({ top: Math.max(0, $('.booking-card').offsetTop - 18), behavior: 'smooth' });
  }
  async function getJSON(url, options) {
    const r = await fetch(url, { headers: { Accept: 'application/json', ...(options?.headers || {}) }, ...options });
    let data = {};
    try { data = await r.json(); } catch (_) {}
    if (!r.ok || data.ok === false) throw new Error(data.message || 'Die Anfrage konnte nicht verarbeitet werden.');
    return data;
  }

  async function loadServices() {
    const root = $('#services');
    root.innerHTML = '<div class="slot-empty">Behandlungen werden geladen …</div>';
    try {
      const data = await getJSON('/api/services/');
      if (!data.services.length) {
        root.innerHTML = '<div class="slot-empty">Zurzeit sind keine Online-Termine freigeschaltet.</div>';
        return;
      }
      root.innerHTML = data.services.map((s) => {
        const price = s.price_label ? `<span>${esc(s.price_label)}</span>` : '';
        return `<button type="button" class="choice-card" data-service='${JSON.stringify(s).replaceAll("'", "&#39;")}'><strong>${esc(s.name)}</strong><p>${esc(s.description || 'Dein Termin wird individuell auf die Behandlung abgestimmt.')}</p><div class="meta"><span>${s.duration_minutes} Min.</span>${price}</div></button>`;
      }).join('');
      root.querySelectorAll('[data-service]').forEach((btn) => btn.addEventListener('click', () => {
        state.service = JSON.parse(btn.dataset.service);
        state.staff = null;
        state.startsAt = null;
        state.slotLabel = null;
        state.dateLabel = null;
        loadStaff();
        go(2);
      }));
    } catch (e) {
      root.innerHTML = '';
      showError(e.message);
    }
  }

  async function loadStaff() {
    const root = $('#staff');
    root.innerHTML = '<div class="slot-empty">Behandler werden geladen …</div>';
    try {
      const data = await getJSON(`/api/staff/?service_id=${encodeURIComponent(state.service.id)}`);
      if (!data.staff.length) {
        root.innerHTML = '<div class="slot-empty">Für diese Behandlung sind aktuell keine Online-Termine freigeschaltet.</div>';
        return;
      }
      root.innerHTML = data.staff.map((s) => {
        const initials = s.name.split(/\s+/).slice(0, 2).map((x) => x[0]).join('');
        const photoUrl = providerPhotos[s.name] || s.photo_url || '';
        const avatar = photoUrl ? `<img src="${esc(photoUrl)}" alt="${esc(s.name)}" loading="lazy" decoding="async">` : esc(initials);
        const doctor = providerTitles[s.name];
        const roleMarkup = doctor
          ? `<span class="doctor-badge">${esc(doctor.badge)}</span><small class="doctor-title">${esc(doctor.title)}</small>`
          : `<small>${esc(s.role)}</small>`;
        return `<button type="button" class="choice-card staff-card" data-staff='${JSON.stringify(s).replaceAll("'", "&#39;")}'><span class="staff-avatar">${avatar}</span><span class="staff-copy"><strong>${esc(s.name)}</strong>${roleMarkup}${s.bio ? `<em>${esc(s.bio)}</em>` : ''}</span><span class="staff-arrow" aria-hidden="true">›</span></button>`;
      }).join('');
      root.querySelectorAll('[data-staff]').forEach((btn) => btn.addEventListener('click', () => {
        state.staff = JSON.parse(btn.dataset.staff);
        state.startsAt = null;
        state.slotLabel = null;
        state.dateLabel = null;
        loadAvailabilityOverview();
        go(3);
      }));
    } catch (e) {
      root.innerHTML = '';
      showError(e.message);
    }
  }

  function formatDate(isoDate) {
    const d = new Date(`${isoDate}T12:00:00`);
    return {
      weekday: new Intl.DateTimeFormat('de-DE', { weekday: 'long' }).format(d),
      short: new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit' }).format(d),
      full: new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(d),
    };
  }

  async function loadAvailabilityOverview() {
    const root = $('#slots');
    root.innerHTML = '<div class="slot-empty">Freie Tage und Uhrzeiten werden geladen …</div>';
    try {
      const q = new URLSearchParams({ service_id: state.service.id, staff_id: state.staff.id, days: 30 });
      const data = await getJSON(`/api/availability/overview/?${q}`);
      if (!data.days.length) {
        root.innerHTML = '<div class="slot-empty slot-empty-card">In den nächsten 30 Tagen ist online kein freier Termin verfügbar. Bitte melde dich direkt bei A+esthetic.</div>';
        return;
      }
      root.innerHTML = data.days.map((day) => {
        const label = formatDate(day.date);
        return `<section class="day-card"><header class="day-head"><div><strong>${esc(label.weekday)}</strong><span>${esc(label.short)}</span></div><small>${day.slots.length} freie ${day.slots.length === 1 ? 'Zeit' : 'Zeiten'}</small></header><div class="day-slots">${day.slots.map((s) => `<button type="button" class="slot" data-start="${esc(s.starts_at)}" data-label="${esc(s.label)}" data-date="${esc(label.full)}">${esc(s.label)}</button>`).join('')}</div></section>`;
      }).join('');
      root.querySelectorAll('.slot').forEach((btn) => btn.addEventListener('click', () => {
        state.startsAt = btn.dataset.start;
        state.slotLabel = btn.dataset.label;
        state.dateLabel = btn.dataset.date;
        renderSummary();
        go(4);
      }));
    } catch (e) {
      root.innerHTML = '';
      showError(e.message);
    }
  }

  function renderSummary(target = '#summary') {
    $(target).innerHTML = `<div class="summary-row"><span>Behandlung</span><strong>${esc(state.service?.name)}</strong></div><div class="summary-row"><span>Behandler</span><strong>${esc(state.staff?.name)}</strong></div><div class="summary-row"><span>Termin</span><strong>${esc(state.dateLabel)} · ${esc(state.slotLabel)} Uhr</strong></div>`;
  }

  $$('[data-back]').forEach((b) => b.addEventListener('click', () => go(Number(b.dataset.back))));
  $$('.progress-dot').forEach((dot) => dot.addEventListener('click', () => go(Number(dot.dataset.progress))));

  const termsLink = $('[data-open-terms]');
  if (termsLink) {
    termsLink.addEventListener('click', (event) => {
      event.preventDefault();
      const box = $('#stornierungsbedingungen');
      box.open = true;
      box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  $('#details-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    clearError();
    if (!state.startsAt) return showError('Bitte wähle zuerst einen freien Termin.');
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const button = form.querySelector('button[type=submit]');
    const raw = Object.fromEntries(new FormData(form).entries());
    const data = {
      ...raw,
      service_id: state.service.id,
      staff_id: state.staff.id,
      starts_at: state.startsAt,
      returning_customer: form.elements.returning_customer.value === 'ja',
      marketing_opt_in: form.elements.marketing_opt_in.checked,
      cancellation_terms_accepted: form.elements.cancellation_terms_accepted.checked,
      privacy_accepted: form.elements.privacy_accepted.checked,
    };
    const idem = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    button.disabled = true;
    button.textContent = 'Termin wird gespeichert …';
    try {
      const result = await getJSON('/api/appointments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value, 'Idempotency-Key': idem },
        body: JSON.stringify(data),
      });
      $('#success-text').textContent = result.appointment.status === 'new'
        ? 'Deine Terminanfrage ist eingegangen und wird von A+esthetic bestätigt.'
        : 'Dein Termin wurde erfolgreich bestätigt.';
      renderSummary('#success-summary');
      go(5);
    } catch (e) {
      showError(e.message);
    } finally {
      button.disabled = false;
      button.textContent = 'Jetzt Termin buchen';
    }
  });

  updateProgress(1);
  loadServices();
})();
