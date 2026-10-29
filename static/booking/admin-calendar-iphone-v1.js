/* Reference-driven iPhone calendar behaviour, preserving Django/API writes.
 * The week strip and the timeline deliberately have different navigation roles:
 * arrows browse weeks, while selecting a day changes the displayed appointments.
 */
(() => {
  'use strict';
  if (document.documentElement.dataset.adminPage !== 'calendar') return;
  const mobile = window.matchMedia('(max-width: 760px)');
  const monthFormat = new Intl.DateTimeFormat('de-DE',{month:'long',year:'numeric'});
  const dateFormat = new Intl.DateTimeFormat('de-DE',{day:'2-digit',month:'long',year:'numeric'});
  const longWeekday = new Intl.DateTimeFormat('de-DE',{weekday:'long'});
  const names = ['Mo','Di','Mi','Do','Fr','Sa','So'];
  const isWeek = () => new URLSearchParams(location.search).get('cal_view') === 'week';
  let strip, picker, monthButton, providerSheet;
  let selectedDate = '', visibleMonday = '', navigating = false, filterOpener = null;

  function parse(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
    if (!match) return null;
    const date = new Date(+match[1],+match[2]-1,+match[3],12);
    if (date.getFullYear() !== +match[1] || date.getMonth() !== +match[2]-1 ||
        date.getDate() !== +match[3]) return null;
    return date;
  }
  function iso(date) {
    return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
  }
  function shift(value, count) {
    const date = parse(value);
    if (!date) return value;
    date.setDate(date.getDate()+count);
    return iso(date);
  }
  function mondayOf(value) {
    const date = parse(value) || new Date();
    date.setDate(date.getDate()-((date.getDay()+6)%7));
    return iso(date);
  }
  function currentDate() {
    return new URLSearchParams(location.search).get('date') || iso(new Date());
  }
  function urlFor(value, mode = isWeek() ? 'week' : 'day') {
    const params = new URLSearchParams(location.search);
    params.set('date',value);
    params.set('cal_view',mode);
    ['notice','focus_block','focus_appointment'].forEach(key=>params.delete(key));
    return location.pathname+'?'+params.toString()+'#kalender';
  }
  function renderHead(value) {
    const date = parse(value);
    if (!date) return;
    const head = document.querySelector('.sb-calendar-shell.is-day .sb-day-head');
    if (!head) return;
    let label = head.querySelector('.sb-reference-day-label');
    if (!label) {
      label = document.createElement('strong');
      label.className = 'sb-reference-day-label';
      head.prepend(label);
    }
    label.textContent = longWeekday.format(date)+', '+
      String(date.getDate()).padStart(2,'0')+'-'+
      String(date.getMonth()+1).padStart(2,'0')+'-'+date.getFullYear();
  }
  function renderWeekHeads() {
    if (!isWeek()) return;
    const dates = [...document.querySelectorAll('.sb-calendar-shell.is-week .sb-day-head')];
    dates.forEach((head,index)=>{
      const date = parse(shift(mondayOf(selectedDate),index));
      if (!date) return;
      let label = head.querySelector('.sb-reference-day-label');
      if (!label) {
        label=document.createElement('strong');
        label.className='sb-reference-day-label';
        head.prepend(label);
      }
      label.textContent=String(date.getDate()).padStart(2,'0')+'-'+
        String(date.getMonth()+1).padStart(2,'0')+'-'+date.getFullYear();
    });
  }
  function scrollWeekTo(value) {
    const shell = document.querySelector('.sb-calendar-shell.is-week');
    const days = shell?.querySelectorAll('.sb-calendar-day');
    if (!shell || !days?.length) return;
    const monday = mondayOf(value);
    const index = (parse(value).getDay()+6)%7;
    const day = days[index];
    if (day) shell.scrollTo({left:day.offsetLeft-days[0].offsetLeft,behavior:'auto'});
  }
  function renderStrip() {
    if (!strip) return;
    const base=parse(visibleMonday);
    if (!base) return;
    const monthDay=parse(shift(visibleMonday,3));
    if (monthButton && monthDay) {
      monthButton.textContent=monthFormat.format(monthDay);
      monthButton.setAttribute('aria-label','Datum wählen: '+monthFormat.format(monthDay));
    }
    if (picker) picker.value=selectedDate;
    strip.classList.toggle('is-week',isWeek());
    const today=iso(new Date());
    strip.replaceChildren();
    for(let i=0;i<7;i++){
      const date=new Date(base);
      date.setDate(base.getDate()+i);
      const value=iso(date);
      const button=document.createElement('button');
      button.type='button';
      button.className='sb-iphone-day';
      button.dataset.date=value;
      button.setAttribute('aria-label',longWeekday.format(date)+' '+dateFormat.format(date));
      button.setAttribute('aria-pressed',value===selectedDate?'true':'false');
      button.classList.toggle('is-active',value===selectedDate);
      button.classList.toggle('is-today',value===today);
      const day=document.createElement('span');
      day.textContent=names[i];
      const number=document.createElement('strong');
      number.textContent=String(date.getDate());
      button.append(day,number);
      button.addEventListener('click',()=>{
        if (isWeek()) {
          selectedDate=value;
          const params=new URLSearchParams(location.search);
          params.set('date',value);
          history.pushState({calendarDate:value},'',location.pathname+'?'+params+'#kalender');
          renderStrip();
          scrollWeekTo(value);
        } else navigateToDay(value);
      });
      strip.appendChild(button);
    }
  }
  async function navigateToDay(value) {
    if (!parse(value)||navigating||value===selectedDate) return;
    if (isWeek()) {location.assign(urlFor(value,'day'));return;}
    navigating=true;
    try {
      if (typeof window.aplusCalendarNavigate==='function') {
        const success=await window.aplusCalendarNavigate(value);
        if (!success) {location.assign(urlFor(value,'day'));return;}
        selectedDate=value;
        visibleMonday=mondayOf(value);
        renderStrip();
        renderHead(value);
      } else location.assign(urlFor(value,'day'));
    } finally {navigating=false;}
  }
  function changeWeek(direction) {
    const next=shift(visibleMonday,7*direction);
    if (isWeek()) {
      location.assign(urlFor(next,'week'));
      return;
    }
    visibleMonday=next; // browsing does NOT accidentally change appointment day
    renderStrip();
  }
  function openDatePicker() {
    if (!picker) return;
    picker.value=selectedDate;
    try {
      if (typeof picker.showPicker==='function') picker.showPicker();
      else {picker.focus();picker.click();}
    } catch(_e) {picker.focus();picker.click();}
  }
  function closeFilter() {
    if (!providerSheet)return;
    providerSheet.remove();
    providerSheet=null;
    filterOpener?.focus({preventScroll:true});
  }
  function openFilter(button) {
    if(providerSheet){closeFilter();return;}
    filterOpener=button;
    const viewMenu=document.querySelector('[data-view-menu]');
    if(viewMenu)viewMenu.hidden=true;
    const backdrop=document.createElement('div');
    backdrop.className='sb-reference-filter-scrim';
    backdrop.setAttribute('role','presentation');
    const sheet=document.createElement('section');
    sheet.className='sb-reference-filter-sheet';
    sheet.setAttribute('role','dialog');
    sheet.setAttribute('aria-modal','true');
    sheet.setAttribute('aria-label','Behandler wählen');
    const head=document.createElement('header');
    head.className='sb-reference-filter-head';
    const label=document.createElement('strong');
    label.textContent='Dienstleister auswählen';
    const close=document.createElement('button');
    close.type='button';close.textContent='×';close.setAttribute('aria-label','Schließen');
    close.addEventListener('click',closeFilter);
    head.append(label,close);sheet.appendChild(head);
    const doctorMode=document.body.dataset.doctorCalendar==='1';
    [...document.querySelectorAll('.sb-provider-switcher .doctor-pill')].forEach(pill=>{
      if(doctorMode && !pill.classList.contains('is-active'))return;
      const choice=document.createElement('button');
      choice.type='button';choice.className='sb-reference-provider';
      choice.setAttribute('aria-pressed',pill.classList.contains('is-active')?'true':'false');
      const person=document.createElement('span');
      person.textContent=pill.querySelector('b')?.textContent?.trim()||'Behandler';
      const count=document.createElement('small');
      count.textContent=pill.querySelector('small')?.textContent?.trim()||'';
      choice.append(person,count);
      choice.addEventListener('click',()=>{
        pill.click();closeFilter();
      });
      sheet.appendChild(choice);
    });
    backdrop.appendChild(sheet);
    backdrop.addEventListener('click',event=>{if(event.target===backdrop)closeFilter();});
    document.body.appendChild(backdrop);
    providerSheet=backdrop;
    close.focus({preventScroll:true});
  }
  function localizedDates() {
    const modalInputs=[...document.querySelectorAll('.sb-modal input[type="date"]')];
    modalInputs.forEach(input=>{
      if(input.closest('.sb-reference-date-field'))return;
      const wrap=document.createElement('span');
      wrap.className='sb-reference-date-field';
      input.parentNode.insertBefore(wrap,input);
      wrap.appendChild(input);
      const text=document.createElement('span');
      text.className='sb-reference-human-date';
      input.insertAdjacentElement('beforebegin',text);
      const update=()=>{
        const date=parse(input.value);
        text.textContent=date?dateFormat.format(date):'Datum wählen';
      };
      input.addEventListener('change',update);
      input.addEventListener('input',update);
      const modal=input.closest('.sb-modal');
      if(modal&&window.MutationObserver) {
        new MutationObserver(()=>{if(modal.classList.contains('is-open'))update();})
          .observe(modal,{attributes:true,attributeFilter:['class']});
      }
      update();
    });
  }
  function updateNoteBlockStatus() {
    const modal=document.querySelector('[data-modal="note"]');
    const enabled=Boolean(modal?.querySelector('input[name="note_blocked"]')?.checked);
    const label=modal?.querySelector('.sb-block-toggle strong');
    const description=modal?.querySelector('.sb-block-toggle div span');
    if(label)label.textContent=enabled?'Zeitraum ist geblockt':'Zeitraum ist nicht geblockt';
    if(description)description.textContent='Zeitraum ist geblockt';
  }
  function initTimeDefaults() {
    ['note','block'].forEach(name=>{
      const node=document.querySelector('[data-modal="'+name+'"]');
      const form=node?.querySelector('form');
      if(!form)return;
      const start=form.querySelector('[name="'+name+'_start"]');
      const end=form.querySelector('[name="'+name+'_end"]');
      if(start&&!start.value)start.value='10:00';
      if(end&&!end.value)end.value='10:15';
    });
  }
  function updateScopeMessage() {
    const value=document.querySelector('[data-modal="note"] input[name="note_scope"]:checked')?.value;
    const message=document.querySelector('[data-modal="note"] .sb-reference-scope-message');
    if(message)message.textContent=value==='staff'?'Diese Notiz gilt für den gewählten Dienstleister':
      value==='service'?'Diese Notiz gilt für die ausgewählte Dienstleistung':
      'Diese Notiz wird für alle angezeigt';
  }
  function mount() {
    if(!mobile.matches)return;
    const nav=document.querySelector('.sb-date-nav');
    const title=nav?.querySelector('.sb-date-title');
    if(!nav||!title||title.querySelector('.sb-iphone-month-button'))return;
    const base=currentDate();
    selectedDate=parse(base)?base:iso(new Date());
    visibleMonday=mondayOf(selectedDate);

    monthButton=document.createElement('button');
    monthButton.type='button';
    monthButton.className='sb-iphone-month-button';
    monthButton.addEventListener('click',openDatePicker);
    title.appendChild(monthButton);
    picker=document.createElement('input');
    picker.type='date';
    picker.className='sb-iphone-date-input';
    picker.setAttribute('aria-label','Datum wählen');
    title.appendChild(picker);
    picker.addEventListener('change',()=>{
      if(!parse(picker.value))return;
      if(isWeek())location.assign(urlFor(picker.value,'week'));
      else navigateToDay(picker.value);
    });
    strip=document.createElement('nav');
    strip.className='sb-iphone-weekstrip';
    strip.setAttribute('aria-label','Kalendertag auswählen');
    nav.insertAdjacentElement('afterend',strip);
    renderStrip();
    renderHead(selectedDate);
    renderWeekHeads();
    document.body.classList.add('sb-iphone-calendar-ready');

    /* Capture arrow taps before old AJAX one-day handlers can run. */
    nav.querySelectorAll('.sb-date-arrow').forEach((arrow,index)=>{
      arrow.setAttribute('aria-label',index===0?'Vorherige Woche':'Nächste Woche');
      arrow.addEventListener('click',event=>{
        event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
        changeWeek(index===0?-1:1);
      },true);
    });
    document.querySelectorAll('[data-iphone-date-open]').forEach(button=>{
      button.addEventListener('click',openDatePicker);
    });
    document.querySelectorAll('[data-iphone-filter-open]').forEach(button=>{
      button.addEventListener('click',()=>openFilter(button));
    });
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&providerSheet)closeFilter();
    });
    window.addEventListener('aplus:calendar-day-changed',event=>{
      if(!parse(event.detail?.date))return;
      selectedDate=event.detail.date;
      visibleMonday=mondayOf(selectedDate);
      renderStrip();
      requestAnimationFrame(()=>renderHead(selectedDate));
    });
    window.addEventListener('popstate',()=>{
      selectedDate=currentDate();
      visibleMonday=mondayOf(selectedDate);
      renderStrip();
      renderHead(selectedDate);
    });
    const shell=document.querySelector('.sb-calendar-shell');
    if(shell){
      let pointerStart=null;
      shell.addEventListener('touchstart',event=>{
        const target=event.target;
        if(isWeek()||event.touches.length!==1||
          target.closest('a,input,select,textarea,.sb-event-menu,.sb-day-hours-edit,.sb-fab')) {
          pointerStart=null;return;
        }
        pointerStart={x:event.touches[0].clientX,y:event.touches[0].clientY,at:Date.now()};
      },{passive:true});
      shell.addEventListener('touchend',event=>{
        if(!pointerStart||!event.changedTouches?.length)return;
        const dx=event.changedTouches[0].clientX-pointerStart.x;
        const dy=event.changedTouches[0].clientY-pointerStart.y;
        const elapsed=Date.now()-pointerStart.at;
        pointerStart=null;
        if(elapsed<850&&Math.abs(dx)>65&&Math.abs(dx)>Math.abs(dy)*1.5){
          navigateToDay(shift(selectedDate,dx<0?1:-1));
        }
      },{passive:true});
      shell.addEventListener('touchcancel',()=>{pointerStart=null;},{passive:true});
    }
    if(isWeek())requestAnimationFrame(()=>scrollWeekTo(selectedDate));
    localizedDates();
    initTimeDefaults();
    const blockToggle=document.querySelector('[data-modal="note"] input[name="note_blocked"]');
    blockToggle?.addEventListener('change',updateNoteBlockStatus);
    updateNoteBlockStatus();
    document.querySelectorAll('[data-modal="note"] input[name="note_scope"]').forEach(input=>input.addEventListener('change',updateScopeMessage));
    updateScopeMessage();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
