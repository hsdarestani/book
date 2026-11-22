/* Dedicated week-strip gesture handler, independent of the legacy calendar
 * loader. Registered in capture phase on window so overlapping elements,
 * iOS touch cancellation and dynamically replaced strips cannot swallow it.
 * In both day and week views, a swipe on the seven-day strip changes the
 * calendar to the corresponding date in the next or previous week.
 */
(() => {
  'use strict';
  const VERSION='20261122-strip3';
  if(document.documentElement.dataset.adminPage!=='calendar')return;
  if(document.documentElement.dataset.weekStripSwipeVersion===VERSION)return;
  document.documentElement.dataset.weekStripSwipeVersion=VERSION;

  const MIN_DISTANCE=48;
  let gesture=null;
  let ignoreClickUntil=0;
  let suppressTouchEndUntil=0;
  let navigationStarted=false;

  function iso(date){
    return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
  }
  function parse(date){
    const m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(date||'');
    if(!m)return null;
    const parsed=new Date(+m[1],+m[2]-1,+m[3],12);
    return parsed.getFullYear()===+m[1]&&parsed.getMonth()===+m[2]-1&&parsed.getDate()===+m[3]?parsed:null;
  }
  function addDays(date,count){
    const d=parse(date);
    if(!d)return date;
    d.setDate(d.getDate()+count);
    return iso(d);
  }
  function monday(date){
    const d=parse(date)||new Date();
    d.setDate(d.getDate()-((d.getDay()+6)%7));
    return iso(d);
  }
  function currentDate(){
    const requested=new URLSearchParams(location.search).get('date');
    return parse(requested)?requested:iso(new Date());
  }
  function activeStrip(){
    return document.querySelector('.sb-reference-date-dock .sb-iphone-weekstrip')||
      document.querySelector('.sb-iphone-weekstrip');
  }
  function withinStrip(x,y){
    const strip=activeStrip();
    if(!strip)return false;
    const r=strip.getBoundingClientRect();
    return r.width>150&&r.height>25&&x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom;
  }
  function begin(x,y,id,source){
    if(navigationStarted||!window.matchMedia('(max-width: 760px)').matches)return;
    gesture=withinStrip(x,y)?{x,y,id,source,at:Date.now()}:null;
  }
  function changeByWeek(direction){
    if(navigationStarted)return;
    const params=new URLSearchParams(location.search);
    const mode=params.get('cal_view')||'day';
    if(mode!=='week'&&mode!=='day')return;
    const selected=currentDate();
    const displayedFirst=activeStrip()?.querySelector('.sb-iphone-day[data-date]')?.dataset.date;
    const weekStart=parse(displayedFirst)?displayedFirst:monday(selected);
    const nextMonday=addDays(weekStart,7*direction);
    // Day view: keep the same weekday selected, but show appointments from
    // the new week. Week view: show the entire next/previous week.
    const weekday=(parse(selected).getDay()+6)%7;
    const target=mode==='week'?nextMonday:addDays(nextMonday,weekday);
    params.set('date',target);
    params.set('cal_view',mode);
    ['notice','focus_block','focus_appointment'].forEach(key=>params.delete(key));
    navigationStarted=true;
    const url=location.pathname+'?'+params.toString()+'#kalender';
    location.assign(url);
  }
  function tryMove(event,x,y,source,id,final){
    if(!gesture||gesture.source!==source||gesture.id!==id||navigationStarted)return;
    const dx=x-gesture.x;
    const dy=y-gesture.y;
    const elapsed=Date.now()-gesture.at;
    if(Math.abs(dy)>35&&Math.abs(dy)>Math.abs(dx)){
      gesture=null; // never steal vertical scrolling
      return;
    }
    if(Math.abs(dx)>=MIN_DISTANCE&&Math.abs(dx)>Math.abs(dy)*1.25&&elapsed<1500){
      gesture=null;
      ignoreClickUntil=Date.now()+850;
      suppressTouchEndUntil=Date.now()+850;
      if(event.cancelable)event.preventDefault();
      event.stopImmediatePropagation();
      changeByWeek(dx<0?1:-1);
    } else if(final){
      gesture=null;
    }
  }
  window.addEventListener('touchstart',event=>{
    if(event.touches.length!==1)return;
    const t=event.touches[0];
    begin(t.clientX,t.clientY,t.identifier,'touch');
  },{capture:true,passive:true});
  window.addEventListener('touchmove',event=>{
    if(!gesture||gesture.source!=='touch'||event.touches.length!==1)return;
    const t=event.touches[0];
    tryMove(event,t.clientX,t.clientY,'touch',t.identifier,false);
  },{capture:true,passive:false});
  window.addEventListener('touchend',event=>{
    if(Date.now()<suppressTouchEndUntil){event.stopImmediatePropagation();return;}
    if(!gesture||gesture.source!=='touch')return;
    for(const t of event.changedTouches){
      if(t.identifier===gesture.id){
        tryMove(event,t.clientX,t.clientY,'touch',t.identifier,true);
        break;
      }
    }
  },{capture:true,passive:false});
  window.addEventListener('touchcancel',()=>{gesture=null;},{capture:true,passive:true});
  window.addEventListener('pointerdown',event=>{
    if(!event.isPrimary)return;
    // Native touchstart supersedes pointerdown whenever both are delivered.
    if(gesture?.source==='touch')return;
    begin(event.clientX,event.clientY,event.pointerId,'pointer');
  },true);
  window.addEventListener('pointermove',event=>{
    if(!event.isPrimary||!gesture||gesture.source!=='pointer')return;
    tryMove(event,event.clientX,event.clientY,'pointer',event.pointerId,false);
  },{capture:true,passive:false});
  window.addEventListener('pointerup',event=>{
    if(!event.isPrimary||!gesture||gesture.source!=='pointer')return;
    tryMove(event,event.clientX,event.clientY,'pointer',event.pointerId,true);
  },{capture:true,passive:false});
  window.addEventListener('pointercancel',()=>{
    if(gesture?.source==='pointer')gesture=null;
  },true);
  window.addEventListener('click',event=>{
    if(Date.now()<ignoreClickUntil&&withinStrip(event.clientX,event.clientY)){
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  },true);
})();
