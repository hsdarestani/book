/* iPhone admin calendar: accessible seven-day chooser, native date picker and
   horizontal day swipe. Reuses the existing authenticated fast day API. */
(() => {
  'use strict';
  if (document.documentElement.dataset.adminPage !== 'calendar') return;
  const phone = window.matchMedia('(max-width:760px)');
  const DAY = 86400000;
  const format = new Intl.DateTimeFormat('de-DE', { month: 'long', year: 'numeric' });
  const weekday = new Intl.DateTimeFormat('de-DE', { weekday: 'short' });
  const days = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  let strip;
  let picker;
  let monthButton;
  let selectedDate = '';
  let navigating = false;

  function fromIso(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    const date = new Date(+match[1], +match[2]-1, +match[3], 12);
    return date.getFullYear() === +match[1] &&
      date.getMonth() === +match[2]-1 && date.getDate() === +match[3] ? date : null;
  }
  function toIso(date) {
    return [date.getFullYear(), String(date.getMonth()+1).padStart(2,'0'), String(date.getDate()).padStart(2,'0')].join('-');
  }
  function shift(value, distance) {
    const date = fromIso(value);
    if (!date) return value;
    date.setDate(date.getDate() + distance);
    return toIso(date);
  }
  function currentIso() {
    return new URLSearchParams(location.search).get('date') || toIso(new Date());
  }
  function dateUrl(value) {
    const params = new URLSearchParams(location.search);
    params.set('date', value);
    params.set('cal_view', 'day');
    params.delete('notice');
    params.delete('focus_block');
    params.delete('focus_appointment');
    return location.pathname + '?' + params.toString() + '#kalender';
  }
  async function goTo(value) {
    if (!fromIso(value) || navigating || value === selectedDate && new URLSearchParams(location.search).get('cal_view') !== 'week') return;
    const url = dateUrl(value);
    if (new URLSearchParams(location.search).get('cal_view') !== 'day') {
      location.assign(url);
      return;
    }
    navigating = true;
    const panel = document.querySelector('.sb-calendar-panel');
    try {
      if (typeof window.aplusCalendarNavigate === 'function') {
        const success = await window.aplusCalendarNavigate(value);
        if (success) {
          render(value);
        } else {
          location.assign(url);
        }
      } else {
        location.assign(url);
      }
    } finally {
      panel?.removeAttribute('data-iphone-navigating');
      navigating = false;
    }
  }
  function render(value) {
    const date = fromIso(value);
    if (!date || !strip) return;
    selectedDate = value;
    if (picker) picker.value = value;
    if (monthButton) {
      monthButton.textContent = format.format(date) + ' ▾';
      monthButton.setAttribute('aria-label', 'Datum wählen: ' + format.format(date));
    }
    const start = new Date(date);
    start.setDate(date.getDate() - ((date.getDay()+6)%7));
    const today = toIso(new Date());
    strip.replaceChildren();
    for (let i=0; i<7; i++) {
      const day = new Date(start);
      day.setDate(start.getDate()+i);
      const iso = toIso(day);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'sb-iphone-day';
      button.dataset.date = iso;
      button.classList.toggle('is-active', iso === value);
      button.classList.toggle('is-today', iso === today);
      button.setAttribute('aria-label', weekday.format(day) + ' ' + new Intl.DateTimeFormat('de-DE',{day:'numeric',month:'long'}).format(day));
      button.setAttribute('aria-pressed', iso === value ? 'true' : 'false');
      const label = document.createElement('span');
      label.textContent = days[i];
      const number = document.createElement('strong');
      number.textContent = String(day.getDate());
      button.append(label, number);
      button.addEventListener('click', () => goTo(iso));
      strip.appendChild(button);
    }
  }
  function mount() {
    if (!phone.matches) return;
    const nav = document.querySelector('.sb-date-nav');
    const title = nav?.querySelector('.sb-date-title');
    if (!nav || !title || nav.querySelector('.sb-iphone-today')) return;
    const today = document.createElement('button');
    today.type = 'button';
    today.className = 'sb-iphone-today';
    today.textContent = 'Heute';
    today.setAttribute('aria-label', 'Zum heutigen Tag');
    today.addEventListener('click', () => goTo(toIso(new Date())));
    nav.appendChild(today);

    monthButton = document.createElement('button');
    monthButton.type = 'button';
    monthButton.className = 'sb-iphone-month-button';
    monthButton.setAttribute('aria-haspopup', 'dialog');
    title.appendChild(monthButton);
    picker = document.createElement('input');
    picker.type = 'date';
    picker.className = 'sb-iphone-date-input';
    picker.setAttribute('aria-label', 'Datum im Kalender wählen');
    title.appendChild(picker);
    monthButton.addEventListener('click', () => {
      picker.value = selectedDate;
      try {
        if (typeof picker.showPicker === 'function') picker.showPicker();
        else { picker.focus(); picker.click(); }
      } catch (_error) { picker.focus(); picker.click(); }
    });
    picker.addEventListener('change', () => {
      if (picker.value) goTo(picker.value);
    });

    strip = document.createElement('nav');
    strip.className = 'sb-iphone-weekstrip';
    strip.setAttribute('aria-label', 'Kalendertag auswählen');
    nav.insertAdjacentElement('afterend', strip);
    render(currentIso());

    const shell = document.querySelector('.sb-calendar-shell');
    if (shell) {
      let start = null;
      shell.addEventListener('touchstart', (event) => {
        const target = event.target;
        if (!phone.matches || !shell.classList.contains('is-day') ||
            event.touches.length !== 1 || target.closest('button,a,input,select,textarea,[role="button"]')) {
          start = null;
          return;
        }
        start = {x: event.touches[0].clientX, y: event.touches[0].clientY, at: Date.now()};
      }, {passive:true});
      shell.addEventListener('touchend', (event) => {
        if (!start || !event.changedTouches.length) return;
        const dx = event.changedTouches[0].clientX - start.x;
        const dy = event.changedTouches[0].clientY - start.y;
        const elapsed = Date.now() - start.at;
        start = null;
        if (elapsed < 800 && Math.abs(dx) >= 65 && Math.abs(dx) > Math.abs(dy)*1.5) {
          goTo(shift(selectedDate, dx < 0 ? 1 : -1));
        }
      }, {passive:true});
      shell.addEventListener('touchcancel', () => {start = null;}, {passive:true});
    }

    /* Calendar API render dispatches after successful day / staff switching. */
    window.addEventListener('aplus:calendar-day-changed', event => {
      if (event.detail?.date) render(event.detail.date);
    });
    window.addEventListener('popstate', () => render(currentIso()));
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, {once:true});
  } else mount();
})();
