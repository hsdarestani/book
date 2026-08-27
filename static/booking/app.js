(() => {
  const state = {
    service: null,
    staff: null,
    startsAt: null,
    slotLabel: null,
    dateLabel: null,
    availabilityDays: [],
    selectedDayIndex: 0,
    currentStep: 1,
    maxStep: 1,
  };

  const providerPhotos = {
    'Frau Ariane Regaei': '/static/booking/staff/ariane-regaei.jpg?v=e0a400ebbcee',
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
        state.availabilityDays = [];
        state.selectedDayIndex = 0;
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
        state.availabilityDays = [];
        state.selectedDayIndex = 0;
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
      weekdayShort: new Intl.DateTimeFormat('de-DE', { weekday: 'short' }).format(d).replace('.', ''),
      day: new Intl.DateTimeFormat('de-DE', { day: '2-digit' }).format(d),
      monthShort: new Intl.DateTimeFormat('de-DE', { month: 'short' }).format(d).replace('.', ''),
      full: new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }).format(d),
    };
  }

  function renderSelectedDay(index, { scroll = true } = {}) {
    const root = $('#slots');
    const day = state.availabilityDays[index];
    if (!day) return;
    state.selectedDayIndex = index;
    state.startsAt = null;
    state.slotLabel = null;
    state.dateLabel = null;

    root.querySelectorAll('.date-chip').forEach((chip) => {
      const selected = Number(chip.dataset.dayIndex) === index;
      chip.classList.toggle('is-active', selected);
      chip.setAttribute('aria-selected', selected ? 'true' : 'false');
      chip.setAttribute('tabindex', selected ? '0' : '-1');
    });

    const label = formatDate(day.date);
    const title = root.querySelector('[data-selected-day-title]');
    const count = root.querySelector('[data-selected-day-count]');
    const timeRoot = root.querySelector('[data-time-slots]');
    if (title) title.textContent = `${label.weekday}, ${label.day}. ${label.monthShort}`;
    if (count) count.textContent = `${day.slots.length} freie ${day.slots.length === 1 ? 'Zeit' : 'Zeiten'}`;
    if (timeRoot) {
      timeRoot.innerHTML = day.slots.map((s) => `<button type="button" class="slot" data-start="${esc(s.starts_at)}" data-label="${esc(s.label)}" data-date="${esc(label.full)}">${esc(s.label)}</button>`).join('');
      timeRoot.querySelectorAll('.slot').forEach((btn) => btn.addEventListener('click', () => {
        state.startsAt = btn.dataset.start;
        state.slotLabel = btn.dataset.label;
        state.dateLabel = btn.dataset.date;
        renderSummary();
        go(4);
      }));
    }

    if (scroll) {
      const active = root.querySelector(`.date-chip[data-day-index="${index}"]`);
      active?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }

  function bindAvailabilityControls() {
    const root = $('#slots');
    const rail = root.querySelector('[data-date-rail]');
    root.querySelectorAll('.date-chip').forEach((chip) => chip.addEventListener('click', () => {
      renderSelectedDay(Number(chip.dataset.dayIndex));
    }));
    root.querySelector('[data-date-prev]')?.addEventListener('click', () => {
      rail?.scrollBy({ left: -Math.max(260, rail.clientWidth * 0.78), behavior: 'smooth' });
    });
    root.querySelector('[data-date-next]')?.addEventListener('click', () => {
      rail?.scrollBy({ left: Math.max(260, rail.clientWidth * 0.78), behavior: 'smooth' });
    });
    rail?.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const delta = event.key === 'ArrowRight' ? 1 : -1;
      const next = Math.max(0, Math.min(state.availabilityDays.length - 1, state.selectedDayIndex + delta));
      renderSelectedDay(next);
      root.querySelector(`.date-chip[data-day-index="${next}"]`)?.focus({ preventScroll: true });
    });
  }

  async function loadAvailabilityOverview() {
    const root = $('#slots');
    root.innerHTML = '<div class="slot-empty">Freie Tage und Uhrzeiten werden geladen …</div>';
    try {
      const q = new URLSearchParams({ service_id: state.service.id, staff_id: state.staff.id, days: 30 });
      const data = await getJSON(`/api/availability/overview/?${q}`);
      if (!data.days.length) {
        root.innerHTML = '<div class="slot-empty slot-empty-card">In den nächsten 30 Tagen ist online kein freier Termin verfügbar. Bitte melde dich direkt bei A+Esthetic.</div>';
        return;
      }
      state.availabilityDays = data.days;
      state.selectedDayIndex = 0;
      root.innerHTML = `
        <div class="availability-picker">
          <div class="date-carousel-shell">
            <button type="button" class="date-nav date-nav-prev" data-date-prev aria-label="Frühere verfügbare Tage">‹</button>
            <div class="date-rail" data-date-rail role="tablist" aria-label="Verfügbare Tage">
              ${data.days.map((day, index) => {
                const label = formatDate(day.date);
                return `<button type="button" class="date-chip${index === 0 ? ' is-active' : ''}" role="tab" aria-selected="${index === 0 ? 'true' : 'false'}" tabindex="${index === 0 ? '0' : '-1'}" data-day-index="${index}"><span>${esc(label.weekdayShort)}</span><strong>${esc(label.day)}</strong><small>${esc(label.monthShort)}</small><em>${day.slots.length}</em></button>`;
              }).join('')}
            </div>
            <button type="button" class="date-nav date-nav-next" data-date-next aria-label="Spätere verfügbare Tage">›</button>
          </div>
          <div class="time-panel">
            <div class="time-panel-head"><div><span>Verfügbare Uhrzeiten</span><strong data-selected-day-title></strong></div><small data-selected-day-count></small></div>
            <div class="time-grid" data-time-slots></div>
          </div>
        </div>`;
      bindAvailabilityControls();
      renderSelectedDay(0, { scroll: false });
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
        ? 'Deine Terminanfrage ist eingegangen und wird von A+Esthetic bestätigt.'
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
