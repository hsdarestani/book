/* A+ Esthetic GOÄ Rechner — screenshot-guided workflow, medically gated calculation.
 * Rapid gross-backwards illustration is NOT a GOÄ invoice. An authoritative server
 * quote from actual, clinically confirmed lines is required before saving any draft.
 */
(()=>{'use strict';
const root=document.querySelector('[data-mlr]');if(!root)return;
const $=s=>root.querySelector(s), $$=s=>[...root.querySelectorAll(s)];
const form=$('[data-goae-full]'), details=$('[data-mlr-details]'), list=$('#goaeLines');
const catalog=JSON.parse(document.getElementById('goaeTariffCatalog')?.textContent||'[]');
const treatmentMap=JSON.parse(document.getElementById('goaeTreatmentMap')?.textContent||'{}');
const catalogByCode=Object.fromEntries(catalog.map(x=>[String(x.number),x]));
const treatmentLabels={
 botox:{title:'Botox',unit:'Zone',plural:'Zonen',hint:'Beispiel: 10 Injektionen je Zone; tatsächliche Anzahl prüfen',max:4,cost:9552,code:'252',injections:10},
 hyaluron:{title:'Hyaluron',unit:'Spritze',plural:'Spritzen',hint:'à 1 ml',max:6,cost:7643,code:'2442'},
 prp:{title:'PRP',unit:'Kit',plural:'Kits',hint:'PRP-Kits; analoge Bewertung ärztlich prüfen',max:3,cost:6000,code:'268',extra:['250']},
 lipolysis:{title:'Lipolyse',unit:'Ampulle',plural:'Ampullen',hint:'Beispiel: 10 Injektionen je Ampulle; tatsächliche Anzahl prüfen',max:6,cost:4000,code:'252',injections:10}
};
const euro=c=>(Math.round(Number(c||0))/100).toLocaleString('de-DE',{style:'currency',currency:'EUR'});
const parseCents=v=>{const str=String(v||'').trim().replace(/\s/g,'').replace(/€/g,'');
 if(!/^(?:\d{1,7})(?:[,.]\d{1,2})?$/.test(str))return null;
 const [eu,ct='']=str.replace(',','.').split('.');
 return Number(eu)*100+Number((ct+'00').slice(0,2));
};
const fmtDate=iso=>{let p=iso.split('-');return p.length===3?p[2]+'.'+p[1]+'.'+p[0]:''};
const toISO=v=>{const m=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v.trim());if(!m)return '';
 const iso=m[3]+'-'+m[2]+'-'+m[1],d=new Date(iso+'T12:00:00');
 return Number.isFinite(d.getTime())&&d.getDate()===Number(m[1])&&d.getMonth()===Number(m[2])-1&&d.getFullYear()===Number(m[3])?iso:'';};
const sel={treatment:'hyaluron',qty:1,verified:null,verifiedHash:null,materialsExplicit:false,clinicalTouched:false,working:false};
const field=(line,key)=>line.querySelector('[data-g="'+key+'"]');
const csrf=form.querySelector('input[name=csrfmiddlewaretoken]');
function rowData(line){
 const val=k=>field(line,k)?.value?.trim()||'';
 return {kind:'service',tariff_source:val('official')?'official_catalog':'manual',
   goae_number:val('goae_number'),goae_description:val('goae_description'),quantity:val('quantity'),
   goae_points:val('goae_points'),goae_base_eur:val('goae_base_eur'),goae_factor:val('goae_factor'),
   goae_category:val('goae_category'),goae_justification:val('goae_justification'),
   goae_vat_rate:$('[data-vat]').value,clinical_confirmed:field(line,'clinical_confirmed').checked};
}
function linesForServer(){
 const lines=[...root.querySelectorAll('.mlr-line')].map(rowData),materialRaw=$('[data-material]').value.trim(),
       material=materialRaw?parseCents(materialRaw):0,vat=$('[data-vat]').value;
 if(lines.some(item=>!item.clinical_confirmed))
   return {error:'Jede GOÄ-Leistung muss von der behandelnden Ärztin oder dem behandelnden Arzt bestätigt werden.'};
 if(material===null)return {error:'Materialwert bitte mit höchstens zwei Nachkommastellen eingeben.'};
 if(material>0){
   const desc=$('[data-material-description]').value.trim();
   const receipt=$('[data-material-receipt]').value.trim();
   const accepted=$('[data-material-confirm]').checked;
   if(!accepted||desc.length<4||!receipt)return {error:'Tatsächliche Auslagen, berechnungsfähiges Material und Belegreferenz bestätigen.'};
   lines.push({kind:'material',goae_description:desc,goae_base_eur:(material/100).toFixed(2),
     quantity:String(sel.qty),goae_vat_rate:vat,material_receipt_reference:receipt,material_eligible:true});
 }
 return {lines};
}
function resetVerification(){sel.verified=null;sel.verifiedHash=null;render();$('#goaeLinesJson').value='';}
function addLine(code){
 const t=document.getElementById('goaeLineTemplate');const line=t.content.firstElementChild.cloneNode(true),dropdown=field(line,'official');
 for(const item of catalog){const opt=document.createElement('option');opt.value=item.number;opt.textContent=item.number+' · '+item.de;dropdown.append(opt);}
 if(code && catalogByCode[code]){
  const item=catalogByCode[code];dropdown.value=String(code);
  field(line,'goae_number').value=String(code);field(line,'goae_description').value=item.de;
  field(line,'goae_points').value=item.points;field(line,'goae_category').value=item.category;
  field(line,'goae_base_eur').value='';
 }
 dropdown.addEventListener('change',()=>{const item=catalogByCode[dropdown.value];
  if(item){field(line,'goae_number').value=item.number;field(line,'goae_description').value=item.de;
   field(line,'goae_points').value=item.points;field(line,'goae_category').value=item.category;field(line,'goae_base_eur').value='';}
  resetVerification();
 });
 line.querySelector('[data-goae-remove]').addEventListener('click',()=>{
  if(list.children.length>1){line.remove();renumber();resetVerification();}
 });
 line.addEventListener('input',()=>{sel.clinicalTouched=true;resetVerification()});
 line.addEventListener('change',()=>{sel.clinicalTouched=true;resetVerification()});
 list.append(line);renumber();
}
function renumber(){$$('.mlr-line').forEach((line,i)=>{line.querySelector('[data-line-title]').textContent='Position '+(i+1)})}
function changeTreatment(t){
 if(!treatmentLabels[t])return;
 sel.treatment=t;sel.qty=Math.min(sel.qty,treatmentLabels[t].max);$('[data-qty]').textContent=sel.qty;
 $$('.mlr-treatment').forEach(button=>{const active=button.dataset.treatment===t;
  button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',String(active));});
 const meta=treatmentLabels[t];
 $('[data-quantity-label]').textContent='Wie viele '+meta.plural+'?';
 $('[data-quantity-hint]').textContent=meta.hint;
 if(sel.clinicalTouched){sel.clinicalTouched=false;$('[data-material-confirm]').checked=false;}
 {
  list.replaceChildren();
  const codes=[meta.code,...(meta.extra||[]),'5','1'];
  for(const code of codes)addLine(code);
  if(!list.children.length)addLine('');
 }
 resetVerification();
}
function desiredTotal(){return parseCents($('[data-target-input]').value)}
function targetOrZero(){return desiredTotal()??0}
// Reference-style backwards calculation, exclusively for non-binding proposals.
 // Official clinical and server confirmation remains mandatory before a draft can be saved.
 const referencePoints={'1':80,'5':80,'250':40,'252':40,'268':130,'2442':900};
 const referenceBase=code=>referencePoints[code]*5.82873;
 const decimalFactor=f=>Number(f).toLocaleString('de-DE',{minimumFractionDigits:1,maximumFractionDigits:4,useGrouping:false});
 function fiscalPreview(){
  const total=targetOrZero(),vat=Number($('[data-vat]').value)/100;
  const meta=treatmentLabels[sel.treatment],raw=$('[data-material]').value.trim();
  const entered=parseCents(raw),illustration=!raw;
  const material=(illustration?meta.cost:(entered??0))*sel.qty;
  const fixed=['5','1',...(meta.extra||[])].map(code=>({code,qty:1,factor:2.3,cents:Math.round(referenceBase(code)*2.3)}));
  const n=meta.injections?meta.injections*sel.qty:1;
  const base=referenceBase(meta.code)*n,fixedFee=fixed.reduce((a,l)=>a+l.cents,0);
  const center=Math.round(total/(1+vat))-material;
  let best=null;
  for(let delta=-4;delta<=4;delta++){
   const fee=center+delta,tax=Math.round(fee*vat)+Math.round(material*vat);
   const gap=Math.abs(fee+material+tax-total);
   if(!best||gap<best.gap)best={fee,tax,gap};
  }
  const factor=(best.fee-fixedFee)/base;
  const minimum=Math.ceil((Math.ceil(base)+fixedFee+material)*(1+vat));
  const impossible=!!raw&&entered===null||factor<1||total<5000||total>300000;
  // A cent adjustment in a proposal is never carried into an issued invoice.
  const tax=total-material-best.fee;
  const proposals=[{code:meta.code,qty:n,factor,cents:best.fee-fixedFee},...fixed];
  return {total,fee:best.fee,material,tax,illustration,impossible,minimum,factor,proposals};
 }
 function syncProposals(p){
  if(p.impossible||sel.clinicalTouched||sel.verified)return;
  const meta=treatmentLabels[sel.treatment];
  for(const line of $$('.mlr-line')){
   const code=field(line,'goae_number').value;
   const proposal=p.proposals.find(x=>x.code===code);
   if(!proposal||!catalogByCode[code])continue;
   // PRP analog description must be individually selected, never silently classified.
   if(sel.treatment==='prp'&&code===meta.code)continue;
   field(line,'quantity').value=String(proposal.qty);
   field(line,'goae_factor').value=decimalFactor(proposal.factor);
  }
 }
function renderPaper(preview){
 $('[data-paper-fee]').textContent=euro(preview.fee);
 $('[data-paper-material]').textContent=euro(preview.material);
 $('[data-paper-tax]').textContent=euro(preview.tax);
 $('[data-paper-total]').textContent=euro(preview.total);
 const selected=$('#goaePatient').selectedOptions?.[0];$('[data-paper-patient]').textContent=selected&&selected.value?selected.textContent.trim().split(' · ')[0]:'Patient: bitte auswählen';
 const date=toISO($('#goaeDateGerman').value);$('[data-paper-date]').textContent=date?fmtDate(date):'–';
 const rows=$('[data-paper-rows]');rows.replaceChildren();
 if(sel.verified&&sel.verified.items?.length){
  sel.verified.items.forEach((line,i)=>{
   const src=sel.verified.lines?.[i]||{};const tr=document.createElement('tr');
   const vals=[line.goae_number||'§ 10',line.description||'Auslage',src.quantity||'1',src.kind==='material'?'–':(src.goae_factor||'–'),euro(line.gross_cents)];
   vals.forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});rows.append(tr);
  });
 }else{
  const row=document.createElement('tr');const col=document.createElement('td');col.colSpan=5;
  if(!preview.impossible&&preview.proposals){
   preview.proposals.forEach(p=>{const tr=document.createElement('tr');const label=catalogByCode[p.code]?.de||'GOÄ-Vorschlag';[p.code,label+(sel.treatment==='prp'&&p.code==='268'?' (analog, zu prüfen)':''),String(p.qty),decimalFactor(p.factor),euro(p.cents)].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});rows.append(tr)});
  }else{col.textContent='Vorschau nicht berechenbar. Eingaben prüfen.';row.append(col);rows.append(row);}
 }
}
function setStatus(title,description,variant='warning'){
 const area=$('[data-law-status]');area.className='mlr-status mlr-status-'+variant;
 area.querySelector('strong').textContent=title;area.querySelector('span').textContent=description;
}
function render(){
 const target=desiredTotal();const calculated=fiscalPreview();syncProposals(calculated);
 $('[data-total]').textContent=euro(calculated.total);
 $('[data-treatment-summary]').textContent=treatmentLabels[sel.treatment].title+' · '+sel.qty+' '+(sel.qty===1?treatmentLabels[sel.treatment].unit:treatmentLabels[sel.treatment].plural)+'\nÄsthetisch, inkl. '+$('[data-vat]').value+' % USt.';
 const preview=sel.verified?sel.verified:(calculated.impossible?{...calculated,fee:0,tax:0}:calculated);
 $('[data-fee]').textContent=euro(preview.fee);$('[data-material-total]').textContent=euro(preview.material);$('[data-tax]').textContent=euro(preview.tax);
 for(const [part,key] of [['fee','fee'],['material','material'],['tax','tax']]){
  $('[data-bar-'+part+']').style.width=(preview.total?Math.max(0,100*preview[key]/preview.total):0)+'%';
 }
 if(target===null||target<5000||target>300000){
  setStatus('Betrag eingeben','Bitte einen gültigen Gesamtbetrag in Euro angeben.','error');
 }else if(sel.verified){
  const gap=Math.abs(sel.verified.total-target);
  setStatus(gap<=1?'✓ GOÄ-Entwurf rechnerisch geprüft':'Gesamtbetrag weicht ab',
   gap<=1?'Positionen wurden serverseitig geprüft. Ärztliche und steuerliche Prüfung bleibt notwendig.':'Die ausgewählten GOÄ-Positionen ergeben '+euro(sel.verified.total)+' statt '+euro(target)+'. Faktoren/Positionen prüfen; keine automatische Anpassung.',''+(gap<=1?'ok':'error'));
 }else if(calculated.impossible){
  setStatus('Preis oder Material prüfen','Der Wunschbetrag deckt Material und Mindestsätze nicht oder die Eingabe ist ungültig. Rechnerischer Mindestbetrag: '+euro(calculated.minimum)+'.','error');
 }else{
  const f=calculated.factor, code=treatmentLabels[sel.treatment].code;
  const note=' Nr. '+code+' · Faktor '+decimalFactor(f)+'. '+(calculated.illustration?'Material ist ein Referenzwert, kein bestätigter Einkaufspreis. ':'')+'Nur Vorschlag; ärztliche Prüfung erforderlich.';
  if(f>3.5)setStatus('Honorarvereinbarung nötig',note+' Vor Behandlung gesondert schriftlich vereinbaren.'+(f>10?' Faktor ungewöhnlich hoch; bitte prüfen.':''),'error');
  else if(f>2.3)setStatus('Begründung nötig',note+' Individuelle Begründung dokumentieren.','warning');
  else setStatus('Im Regelrahmen (Vorschau)',note,'ok');
 }
 renderPaper(preview);
 $('[data-material-notice]').hidden=!(calculated.material/sel.qty>2556);
}
function setMessage(msg,kind='error'){const el=$('[data-goae-feedback]');el.textContent=msg;el.className='mlr-feedback '+kind;}
async function verify(){
 const target=desiredTotal();if(target===null||target<100){setMessage('Zuerst einen gültigen Gesamtbetrag eingeben.');return false;}
 if(!$('#goaePatient').value){setMessage('Patient auswählen.');details.open=true;$('#goaePatient').focus();return false;}
 const date=toISO($('#goaeDateGerman').value);$('#goaeDateIso').value=date;
 if(!date){setMessage('Leistungsdatum bitte als TT.MM.JJJJ eingeben.');details.open=true;$('#goaeDateGerman').focus();return false;}
 if(!$('[data-material]').value.trim()){setMessage('Tatsächlichen Materialwert eingeben (0,00 falls keine Auslage).');details.open=true;return false;}
 const source=linesForServer();if(source.error){setMessage(source.error);details.open=true;return false;}
 if(!source.lines.length){setMessage('Mindestens eine tatsächlich erbrachte Leistung wählen.');return false;}
 const sig=JSON.stringify(source.lines);
 setMessage('GOÄ-Berechnung wird geprüft …','');
 let response,data;
 try{
  response=await fetch('/verwaltung/api/goae-quote/',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf.value},body:JSON.stringify({lines:source.lines})});
  data=await response.json();
 }catch(err){setMessage('GOÄ-Rechner momentan nicht erreichbar.');return false;}
 if(!response.ok||!data.ok){setMessage(data.message||'GOÄ-Positionen oder Auslagen nicht zulässig.');return false;}
 const total=Number(data.total_cents)||0,fee=(data.items||[]).reduce((sum,x)=>sum+(x.goae_number?x.net_cents:0),0);
 const material=(data.items||[]).reduce((sum,x)=>sum+(!x.goae_number?x.net_cents:0),0);
 const tax=Number(data.tax_cents)||0;
 sel.verified={total,fee,material,tax,items:data.items,lines:source.lines};
 sel.verifiedHash=sig;render();
 const matched=Math.abs(total-target)<=1;
 setMessage(matched?'Serverberechnung erfolgreich. GOÄ-Entwurf kann gespeichert werden.':'Rechnerisch geprüft, aber Wunschpreis und GOÄ-Positionen stimmen nicht überein: '+euro(total)+' statt '+euro(target)+'. Bitte Faktoren und Angaben prüfen.',matched?'ok':'error');
 return matched;
}
function syncSlider(){const value=desiredTotal();if(value!==null&&value>=50){$('[data-target-slider]').value=Math.max(50,Math.min(1000,value/100));}}
$$('.mlr-treatment').forEach(b=>b.addEventListener('click',()=>changeTreatment(b.dataset.treatment)));
$('[data-qty-minus]').addEventListener('click',()=>{sel.qty=Math.max(1,sel.qty-1);$('[data-qty]').textContent=sel.qty;resetVerification()});
$('[data-qty-plus]').addEventListener('click',()=>{sel.qty=Math.min(treatmentLabels[sel.treatment].max,sel.qty+1);$('[data-qty]').textContent=sel.qty;resetVerification()});
$('[data-target-input]').addEventListener('input',()=>{syncSlider();resetVerification()});
$('[data-target-slider]').addEventListener('input',e=>{$('[data-target-input]').value=String(e.target.value);resetVerification()});
$$('[data-preset]').forEach(b=>b.addEventListener('click',()=>{$('[data-target-input]').value=b.dataset.preset;syncSlider();resetVerification()}));
$$('[data-material],[data-vat],[data-material-confirm],[data-material-receipt],[data-material-description]').forEach(el=>{
 el.addEventListener('input',()=>{if(el.matches('[data-material]'))sel.materialsExplicit=true;resetVerification()});
 el.addEventListener('change',resetVerification);
});
$('#goaePatient').addEventListener('change',render);
$('#goaeDateGerman').addEventListener('input',()=>{$('#goaeDateIso').value='';resetVerification()});
$('[data-native-date]').addEventListener('change',e=>{if(e.target.value)$('#goaeDateGerman').value=fmtDate(e.target.value);resetVerification()});
$('[data-open-calendar]').addEventListener('click',()=>{
 const input=$('[data-native-date]');input.value=toISO($('#goaeDateGerman').value);
 if(typeof input.showPicker==='function')input.showPicker();else{input.focus();input.click()}
});
$('[data-goae-add]').addEventListener('click',()=>{addLine('');sel.clinicalTouched=true;resetVerification()});
$('[data-goae-preview]').addEventListener('click',()=>verify());
$('[data-open-details]').addEventListener('click',()=>{details.open=true;details.scrollIntoView({behavior:'smooth',block:'start'})});
$('[data-reset]').addEventListener('click',()=>{
 sel.qty=1;sel.clinicalTouched=false;$('[data-qty]').textContent='1';
 $('[data-target-input]').value='260';$('[data-target-slider]').value='260';
 $('[data-material]').value='';$('[data-material-receipt]').value='';$('[data-material-description]').value='';$('[data-material-confirm]').checked=false;
 changeTreatment('hyaluron');setMessage('Alle Beispielwerte zurückgesetzt; Patientendaten bleiben erhalten.','');
});
$('[data-print-simulation]').addEventListener('click',()=>{render();window.print()});
form.addEventListener('submit',async ev=>{
 ev.preventDefault();if(sel.working)return;
 const data=linesForServer();if(data.error){setMessage(data.error);details.open=true;return;}
 const sig=JSON.stringify(data.lines||[]);
 if(!sel.verified||sel.verifiedHash!==sig||Math.abs(sel.verified.total-targetOrZero())>1){
  details.open=true;if(!await verify())return;
 }
 if(!form.reportValidity()){details.open=true;form.reportValidity();return;}
 if(!toISO($('#goaeDateGerman').value)){setMessage('Ungültiges Leistungsdatum.');return;}
 const button=form.querySelector('.mlr-save');button.disabled=true;sel.working=true;
 $('#goaeDateIso').value=toISO($('#goaeDateGerman').value);
 $('#goaeLinesJson').value=JSON.stringify(data.lines);
 HTMLFormElement.prototype.submit.call(form);
});
const today=new Date();$('[data-today]').textContent=today.toLocaleDateString('de-DE');
$('#goaeDateGerman').value=today.toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric'});
changeTreatment('hyaluron');syncSlider();render();
})();