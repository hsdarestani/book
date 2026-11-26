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
 botox:{title:'Botox',unit:'Zone',plural:'Zonen',hint:'Beispiel: 10 Injektionen je Zone; tatsächliche Anzahl prüfen',max:4,cost:9552,code:'252',injections:10,injMax:30},
 hyaluron:{title:'Hyaluron',unit:'Spritze',plural:'Spritzen',hint:'à 1 ml',max:6,cost:7643,code:'2442'},
 prp:{title:'PRP',unit:'Kit',plural:'Kits',hint:'PRP-Kits; analoge Bewertung ärztlich prüfen',max:3,cost:6000,code:'268',extra:['250']},
 lipolysis:{title:'Lipolyse',unit:'Ampulle',plural:'Ampullen',hint:'Beispiel: 10 Injektionen je Ampulle; tatsächliche Anzahl prüfen',max:6,cost:4000,code:'252',injections:10,injMax:20}
};
const euro=c=>(Math.round(Number(c||0))/100).toLocaleString('de-DE',{style:'currency',currency:'EUR'});
const parseCents=v=>{let str=String(v||'').trim().replace(/\s/g,'').replace(/€/g,'');
 if(/^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(str))str=str.replace(/\./g,'');
 if(!/^(?:\d{1,7})(?:[,.]\d{1,2})?$/.test(str))return null;
 const [eu,ct='']=str.replace(',','.').split('.');
 return Number(eu)*100+Number((ct+'00').slice(0,2));
};
const fmtDate=iso=>{let p=iso.split('-');return p.length===3?p[2]+'.'+p[1]+'.'+p[0]:''};
const toISO=v=>{const m=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(v.trim());if(!m)return '';
 const iso=m[3]+'-'+m[2]+'-'+m[1],d=new Date(iso+'T12:00:00');
 return Number.isFinite(d.getTime())&&d.getDate()===Number(m[1])&&d.getMonth()===Number(m[2])-1&&d.getFullYear()===Number(m[3])?iso:'';};
const sel={fixed:{},reasonValues:{},reasonSignature:'',injections:null,reasonText:'',reasonTreatment:null,treatment:'hyaluron',qty:1,verified:null,verifiedHash:null,materialsExplicit:false,clinicalTouched:false,working:false,quoting:false,revision:0};
const field=(line,key)=>line.querySelector('[data-g="'+key+'"]');
const csrf=form.querySelector('input[name=csrfmiddlewaretoken]');
function rowData(line){
 const val=k=>field(line,k)?.value?.trim()||'';
 const main=val('goae_number')===treatmentLabels[sel.treatment].code;
 const agreement=main&&Number(val('goae_factor').replace(',','.'))>3.5?{agreement_confirmed:$('[data-agreement-confirm]').checked,agreement_document_id:$('[data-agreement-document]').value,agreement_date:$('[data-agreement-date]').value,agreement_amount_eur:$('[data-agreement-amount]').value}:{};
 return {...agreement,analog:field(line,'analog').checked,analog_confirmed:field(line,'analog_confirmed').checked,kind:'service',tariff_source:val('official')?'official_catalog':'manual',
   goae_number:val('goae_number'),goae_description:val('goae_description'),quantity:val('quantity'),
   goae_points:val('goae_points'),goae_base_eur:val('goae_base_eur'),goae_factor:val('goae_factor'),
   goae_category:val('goae_category'),goae_justification:val('goae_justification'),
   goae_vat_rate:$('[data-vat]').value,clinical_confirmed:field(line,'clinical_confirmed').checked};
}
const materialNames={botox:'Botulinumtoxin',hyaluron:'Hyaluronsäurefiller',prp:'PRP-Kit',lipolysis:'Lipolyse-Präparat'};
function readMaterials(){
 const meta=treatmentLabels[sel.treatment],raw=$('[data-material]').value.trim();
 const primary={description:$('[data-material-description]').value.trim(),qty:Number($('[data-material-qty]').value),cost:raw?parseCents(raw):meta.cost,receipt:$('[data-material-receipt]').value.trim(),confirmed:$('[data-material-confirm]').checked,example:!raw};
 const extra=$$('[data-extra-material]').map(row=>({description:row.querySelector('[data-m-description]').value.trim(),qty:Number(row.querySelector('[data-m-qty]').value),cost:parseCents(row.querySelector('[data-m-cost]').value),receipt:row.querySelector('[data-m-receipt]').value.trim(),confirmed:row.querySelector('[data-m-confirm]').checked,example:false}));
 const rows=[primary,...extra.filter(m=>m.description||m.cost!==null||m.receipt)];
 const invalid=rows.some((m,i)=>m.cost===null||!Number.isInteger(m.qty)||m.qty<1||m.qty>20||m.cost<0||m.cost>50000||(i>0&&(!m.description||m.cost<100))||(i===0&&sel.treatment==='botox'&&m.cost>0&&(m.cost<2000||m.cost>20000)));
 return {rows,invalid,total:rows.reduce((sum,m)=>sum+(m.cost??0)*m.qty,0),example:primary.example};
}
function linesForServer(){
 const lines=$$('.mlr-line').map(rowData), vat=$('[data-vat]').value;
 if(lines.some(item=>item.analog&&!item.analog_confirmed))return {error:'Analogleistung und Gleichwertigkeit ärztlich bestätigen.'};
 if(lines.some(item=>!item.clinical_confirmed))return {error:'Jede GOÄ-Leistung muss von der behandelnden Ärztin oder dem behandelnden Arzt bestätigt werden.'};
 const materials=readMaterials();
 if(materials.invalid)return {error:'Material: Bezeichnung, Anzahl und Nettopreis prüfen.'};
 if(materials.example)return {error:'Tatsächlichen Materialwert eingeben (0,00 falls keine Auslage).'};
 for(const m of materials.rows){
  if(m.cost===0)continue;
  if(!m.confirmed||m.description.length<4||!m.receipt)return {error:'Jede tatsächliche Auslage mit Beleg und Berechnungsfähigkeit bestätigen.'};
  lines.push({kind:'material',goae_description:m.description,goae_base_eur:(m.cost/100).toFixed(2),quantity:String(m.qty),goae_vat_rate:vat,material_receipt_reference:m.receipt,material_eligible:true});
 }
 if(vat==='0'&&!diagnosisText())return {error:'Bei medizinischer Abrechnung die dokumentierte Diagnose angeben.'};
 return {lines};
}
function resetMaterials(){
 $('[data-material]').value='';$('[data-material-description]').value='';$('[data-material-receipt]').value='';$('[data-material-confirm]').checked=false;
 $('[data-material-qty]').value=String(sel.qty);$('[data-material]').placeholder=(treatmentLabels[sel.treatment].cost/100).toFixed(2).replace('.',',');
 $('[data-material-description]').placeholder=materialNames[sel.treatment];$('[data-extra-materials]').replaceChildren();
}
function addMaterial(){
 if($$('[data-extra-material]').length>=19)return;
 const row=document.getElementById('goaeMaterialTemplate').content.firstElementChild.cloneNode(true);
 row.querySelector('[data-material-remove]').addEventListener('click',()=>{row.remove();resetClinicalProposal()});
 row.addEventListener('input',e=>{if(!e.target.matches('[data-m-confirm]')){row.querySelector('[data-m-confirm]').checked=false;resetClinicalProposal();}else resetVerification()});
 $('[data-extra-materials]').append(row);
}
function buildFixed(){
 sel.fixed=Object.fromEntries(['1','5',...(treatmentLabels[sel.treatment].extra||[])].map(code=>[code,code==='250'?'2,3':'2,3']));
 const wrap=$('[data-fixed-factors]');wrap.replaceChildren();
 for(const code of Object.keys(sel.fixed)){
  const label=document.createElement('label'),input=document.createElement('input');
  input.type='text';input.inputMode='decimal';input.value=sel.fixed[code];input.dataset.fixedCode=code;
  label.append(document.createTextNode('Faktor Nr. '+code+' '),input);
  input.addEventListener('input',()=>{sel.fixed[code]=input.value;resetClinicalProposal()});wrap.append(label);
 }
}
function resetVerification(){sel.revision++;sel.verified=null;sel.verifiedHash=null;render();$('#goaeLinesJson').value='';}
function resetClinicalProposal(){
 $('[data-agreement-confirm]').checked=false;
 for(const line of $$('.mlr-line'))field(line,'clinical_confirmed').checked=false;
 sel.clinicalTouched=false;resetVerification();
}
function addLine(code){
 const t=document.getElementById('goaeLineTemplate');const line=t.content.firstElementChild.cloneNode(true),dropdown=field(line,'official');
 for(const item of catalog){const opt=document.createElement('option');opt.value=item.number;opt.textContent=item.number+' · '+item.de;dropdown.append(opt);}
 if(code && catalogByCode[code]){
  const item=catalogByCode[code];dropdown.value=String(code);
  field(line,'goae_number').value=String(code);field(line,'goae_description').value=item.de;
  field(line,'goae_points').value=item.points;field(line,'goae_category').value=item.category;
  field(line,'goae_base_eur').value='';
  if(code==='268'&&sel.treatment==='prp'){field(line,'analog').checked=true;field(line,'goae_description').value='';}
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
 if(t===sel.treatment&&list.children.length)return;
 if(t!==sel.treatment){$('[data-material]').value='';$('[data-material-description]').value='';$('[data-material-receipt]').value='';$('[data-material-confirm]').checked=false;}
 $('[data-agreement-confirm]').checked=false;sel.treatment=t;sel.injections=null;sel.reasonText='';sel.reasonTreatment=null;sel.reasonValues={};sel.reasonSignature='';sel.qty=Math.min(sel.qty,treatmentLabels[t].max);$('[data-qty]').textContent=sel.qty;
 $$('.mlr-treatment').forEach(button=>{const active=button.dataset.treatment===t;
  button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',String(active));});
 const meta=treatmentLabels[t];resetMaterials();buildFixed();
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
  const meta=treatmentLabels[sel.treatment],materials=readMaterials(),illustration=materials.example;
  const material=materials.total;
  const fixed=['5','1',...(meta.extra||[])].map(code=>{const raw=String(sel.fixed[code]??'2,3');const factor=/^\d+(?:[,.]\d{1,4})?$/.test(raw)?Number(raw.replace(',','.')):NaN;return {code,qty:1,factor,cents:Math.round(referenceBase(code)*factor)};});
  const fixedInvalid=fixed.some(x=>!Number.isFinite(x.factor)||x.factor<1||x.factor>(x.code==='250'?2.5:3.5));
  const n=meta.injections?(sel.injections??meta.injections*sel.qty):1;
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
  const impossible=materials.invalid||fixedInvalid||factor<1||total<5000||total>300000||!Number.isInteger(n)||n<1||(meta.injections&&n>meta.injMax*sel.qty);
  // A cent adjustment in a proposal is never carried into an issued invoice.
  const tax=total-material-best.fee;
  const proposals=[{code:meta.code,qty:n,factor,cents:best.fee-fixedFee},...fixed];
  return {total,fee:best.fee,material,tax,illustration,impossible,minimum,factor,proposals,base,fixedFee,vat,materials:materials.rows};
 }
 function syncProposals(p){
  if(p.impossible||sel.clinicalTouched||sel.verified)return;
  const meta=treatmentLabels[sel.treatment];
  for(const line of $$('.mlr-line')){
   const code=field(line,'goae_number').value;
   const proposal=p.proposals.find(x=>x.code===code);
   if(!proposal||!catalogByCode[code])continue;
   // PRP analog description must be individually selected, never silently classified.
   // Analog status is explicit and the physician must supply the actual service description.
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
 $('[data-paper-diagnosis]').textContent=diagnosisText()?'Diagnose / Behandlungsanlass: '+diagnosisText():'';
 const d=$('[data-invoice-date]').value;$('[data-today]').textContent=d?fmtDate(d):'–';
 const due=$('[data-due-date]').value||(d?addDays(d,14):'');$('[data-paper-due]').textContent=due?'Zahlbar bis (Vorschau): '+fmtDate(due):'';
 const rows=$('[data-paper-rows]');rows.replaceChildren();
 if(sel.verified&&sel.verified.items?.length){
  sel.verified.items.forEach((line,i)=>{
   const src=sel.verified.lines?.[i]||{};const tr=document.createElement('tr');
   const vals=[line.goae_number||'§ 10',line.description||'Auslage',src.quantity||'1',src.kind==='material'?'–':(src.goae_factor||'–'),euro(line.net_cents)];
   vals.forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});rows.append(tr);
  });
 }else{
  const row=document.createElement('tr');const col=document.createElement('td');col.colSpan=5;
  if(!preview.impossible&&preview.proposals){
   preview.materials.filter(m=>m.cost>0).forEach(m=>{const tr=document.createElement('tr');['§ 10',m.description||materialNames[sel.treatment],String(m.qty),'–',euro(m.cost*m.qty)].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});rows.append(tr)});
   preview.proposals.forEach(p=>{const tr=document.createElement('tr');const label=catalogByCode[p.code]?.de||'GOÄ-Vorschlag';[p.code,label+(sel.treatment==='prp'&&p.code==='268'?' (analog, zu prüfen)':''),String(p.qty),decimalFactor(p.factor),euro(p.cents)].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});rows.append(tr)});
  }else{col.textContent='Vorschau nicht berechenbar. Eingaben prüfen.';row.append(col);rows.append(row);}
 }
}
function setStatus(title,description,variant='warning'){
 const area=$('[data-law-status]');area.className='mlr-status mlr-status-'+variant;
 area.querySelector('strong').textContent=title;area.querySelector('span').textContent=description;
}
// Reference option catalogue, grouped by actual billed number and treatment.
const reasonOptions=[
 ['1','Ausführliche Beratung zu Alternativen und Risiken bei Erstbehandlung'],
 ['1','Erhöhter Beratungsbedarf nach Vorbehandlungen mit anderen Präparaten'],
 ['1','Erschwerte Verständigung (Sprachbarriere), verlängertes Gespräch'],
 ['1','Ausgeprägte Behandlungsangst, verlängertes Aufklärungsgespräch'],
 ['1','Erhöhter Beratungsaufwand wegen relevanter Medikation'],
 ['5','Mimikanalyse mehrerer Gesichtsregionen in Ruhe und Bewegung'],
 ['5','Erschwerte Untersuchung bei ausgeprägter Gesichtsasymmetrie'],
 ['5','Kontrolle auf Restmaterial oder Knötchen nach Vorbehandlung'],
 ['5','Narben oder Voroperationen im Behandlungsgebiet'],
 ['252','Ausgeprägte Muskelaktivität, dadurch erhöhte Injektionszahl und Präzisionsanforderung','botox'],
 ['252','Asymmetrische Muskelaktivität, seitengetrennte Dosierung erforderlich','botox'],
 ['252','Injektion nahe Gefäßen und Nerven (z. B. periorbital), erhöhte Präzision','botox'],
 ['252','Viele Injektionspunkte auf engem Raum, erhöhter Zeitaufwand'],
 ['252','Dünne, vulnerable Haut mit Hämatomneigung, besonders vorsichtiges Vorgehen'],
 ['252','Ungleichmäßige Fettverteilung, individuelle Injektionsplanung','lipolysis'],
 ['2442','Erhöhtes Gefäßrisiko im Areal (z. B. Nasolabial, Glabella), Kanülentechnik, verlängerte Behandlungszeit'],
 ['2442','Ausgeprägter Volumenverlust, Unterfütterung in mehreren Ebenen'],
 ['2442','Korrektur einer Asymmetrie, seitengetrennte Dosierung'],
 ['2442','Narbiges oder fibrotisches Gewebe, erhöhter Injektionswiderstand'],
 ['2442','Vorbehandlung mit Fremdmaterial, erschwerte Applikation'],
 ['2442','Lippenkonturierung mit hoher Präzisionsanforderung'],
 ['250','Erschwerte Venenpunktion, mehrere Punktionsversuche'],
 ['268','Behandlung großer Areale (z. B. gesamte Kopfhaut), erhöhter Zeitaufwand'],
 ['268','Mehrere Injektionsebenen in einer Sitzung'],
 ['*','Erhöhte Schmerzempfindlichkeit, Behandlung in Etappen mit Pausen'],
 ['*','Vasovagale Reaktion, Unterbrechung und verlängerte Behandlungszeit'],
 ['*','Erhöhte Blutungsneigung, aufwendige Blutstillung'],
 ['*','Eingeschränkte Lagerung oder Mobilität, erschwerte Behandlungsbedingungen']
];
const diagnoses={
 aest:['Ästhetische Behandlung auf Wunsch, keine medizinische Indikation','Mimische Falten (Stirn / Glabella / periorbital), ästhetische Indikation','Altersbedingter Volumenverlust, ästhetische Indikation','Lokalisierte Fettansammlung, ästhetische Indikation','Hautalterung / Elastizitätsverlust, ästhetische Indikation'],
 med:['R61.0 Hyperhidrose, umschrieben','F45.8 Bruxismus','L91.0 Hypertrophe Narbe / Keloid','L90.5 Narben und Fibrosen der Haut','L64.9 Alopecia androgenetica (PRP Kopfhaut)']
};
function localISO(d){return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')}
function addDays(iso,n){const d=new Date(iso+'T12:00:00');d.setDate(d.getDate()+n);return localISO(d)}
function buildDiagnoses(){
 const med=$('[data-vat]').value==='0',select=$('[data-diagnosis]');
 select.replaceChildren();
 if(med)select.append(new Option('Bitte wählen …',''));
 for(const text of diagnoses[med?'med':'aest'])select.append(new Option(text,text));
 select.append(new Option('Eigener Text …','custom'));
 if(!med)select.append(new Option('Keine Angabe',''));
 $('[data-diagnosis-custom-wrap]').hidden=true;$('[data-diagnosis-custom]').value='';
}
function diagnosisText(){const v=$('[data-diagnosis]').value;return v==='custom'?$('[data-diagnosis-custom]').value.trim():v}
const threshold=code=>code==='250'?1.8:2.3;
const ceiling=code=>code==='250'?2.5:3.5;
function reasonChanged(code,box){
 const values=sel.reasonValues[code]={selected:[...box.querySelectorAll('input[type=checkbox]:checked')].map(e=>e.value),custom:box.querySelector('[data-reason-custom]').value};
 const reason=[...values.selected,values.custom.trim()].filter(Boolean).join('; ');
 const line=$$('.mlr-line').find(l=>field(l,'goae_number').value===code);
 if(line){field(line,'goae_justification').value=reason;field(line,'clinical_confirmed').checked=false;}
 resetVerification();
}
function renderAdditional(p){
 const meta=treatmentLabels[sel.treatment],inj=$('[data-injection-count]');
 $('[data-injection-wrap]').hidden=!meta.injections;
 if(meta.injections){inj.max=String(meta.injMax*sel.qty);if(document.activeElement!==inj)inj.value=String(sel.injections??meta.injections*sel.qty);}
 const needed=p.impossible?[]:p.proposals.filter(x=>x.factor>threshold(x.code)+1e-9);
 const high=needed.some(x=>x.factor>ceiling(x.code));
 $('[data-agreement-evidence]').hidden=!high||sel.treatment==='prp';
 $('[data-reason-section]').hidden=!needed.length;
 $('[data-reason-status]').textContent=needed.map(x=>'Nr. '+x.code+' · Faktor '+decimalFactor(x.factor)+(x.factor>ceiling(x.code)?' · Vereinbarung erforderlich':' · Begründung erforderlich')).join(' · ');
 const sig=sel.treatment+'|'+needed.map(x=>x.code).join(',');
 if(sig!==sel.reasonSignature){
  sel.reasonSignature=sig;const wrap=$('[data-reason-options]');wrap.replaceChildren();
  for(const entry of needed){
   const code=entry.code,values=sel.reasonValues[code]||{selected:[],custom:''};
   const box=document.createElement('div');box.dataset.reasonCode=code;box.style.marginBottom='12px';
   const title=document.createElement('strong');title.textContent='Nr. '+code;box.append(title);
   const dd=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Begründung wählen …';dd.append(summary);
   for(const [number,text,treatment] of reasonOptions.filter(([n,_,t])=>(n===code||n==='*')&&(!t||t===sel.treatment))){
    const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=text;input.checked=values.selected.includes(text);
    input.addEventListener('change',()=>reasonChanged(code,box));label.append(input,document.createTextNode(' '+text));label.style.display='block';dd.append(label);
   }
   box.append(dd);const custom=document.createElement('input');custom.type='text';custom.dataset.reasonCustom='';custom.maxLength=100;custom.placeholder='Eigene Begründung Nr. '+code;custom.value=values.custom;custom.addEventListener('input',()=>reasonChanged(code,box));box.append(custom);wrap.append(box);
  }
 }
 const maxPrice=f=>{
  const fixed=p.proposals.slice(1).reduce((sum,x)=>sum+Math.round(referenceBase(x.code)*Math.min(x.factor,f===2.3?threshold(x.code):ceiling(x.code))),0);
  return Math.floor((p.base*f+fixed+p.material)*(1+p.vat)/100)*100;
 };
 const valid=Number.isFinite(p.base)&&Number.isFinite(p.fixedFee)&&p.base>0;
 $('[data-price-boundaries]').textContent=valid?'Ohne Begründung: bis '+euro(maxPrice(2.3))+' · Ohne Honorarvereinbarung: bis '+euro(maxPrice(3.5)):'Eingaben prüfen.';
 for(const button of $$('[data-boundary]')){button.disabled=!valid;button.dataset.price=String(maxPrice(Number(button.dataset.boundary))/100);}
 $('[data-agreement-preview]').hidden=!high;
}
function printAgreement(){
 const p=fiscalPreview(),meta=treatmentLabels[sel.treatment],patient=$('#goaePatient');
 if(p.impossible||p.factor<=3.5)return;
 if(!patient.value){setMessage('Patient bzw. Zahlungspflichtigen vor Erstellung auswählen.');details.open=true;patient.focus();return;}
 if(sel.treatment==='prp'){setMessage('PRP-Analogbewertung muss vor einer Vereinbarung individuell ärztlich geprüft werden.');details.open=true;return;}
 const code=meta.code,label=catalogByCode[code]?.de;
 if(!label){setMessage('Amtliche Leistungsbezeichnung fehlt.');return;}
 const frame=document.createElement('iframe');frame.title='Honorarvereinbarung Druckvorschau';
 frame.style.position='fixed';frame.style.width='1px';frame.style.height='1px';frame.style.border='0';document.body.append(frame);
 const doc=frame.contentDocument;doc.title='Honorarvereinbarung – Entwurf';
 const style=doc.createElement('style');style.textContent='@page{size:A4;margin:22mm}body{font:14px Arial,sans-serif;color:#111;line-height:1.5}table{width:100%;border-collapse:collapse;margin:24px 0}th,td{border-bottom:1px solid #555;text-align:left;padding:10px}h1{font-size:22px}';doc.head.append(style);
 const add=(tag,value,parent=doc.body)=>{const e=doc.createElement(tag);e.textContent=value;parent.append(e);return e;};
 add('h1','Honorarvereinbarung gemäß § 2 GOÄ – Entwurf');
 add('p','Ärztin / Arzt: __________________________________');
 add('p','Zahlungspflichtige Person: '+patient.selectedOptions[0].textContent.trim().split(' · ')[0]);
 const table=doc.createElement('table');doc.body.append(table);
 const headers=doc.createElement('tr');table.append(headers);['Nr.','Leistung','Anzahl','Faktor','Vereinbarter Betrag (netto)'].forEach(x=>add('th',x,headers));
 const main=p.proposals[0],row=doc.createElement('tr');table.append(row);const f=Math.round(main.factor*10000)/10000, agreed=Math.round(referenceBase(code)*f)*main.qty;[code,label,String(main.qty),decimalFactor(f),euro(agreed)].forEach(x=>add('td',x,row));
 add('p','Eine vollständige Erstattung der vereinbarten Vergütung durch Erstattungsstellen ist möglicherweise nicht gewährleistet.');
 add('p','Ort, Datum: __________________________________');
 add('p','Unterschrift Ärztin / Arzt: __________________________');
 add('p','Unterschrift zahlungspflichtige Person: __________________________');
 frame.contentWindow.addEventListener('afterprint',()=>frame.remove(),{once:true});frame.contentWindow.focus();frame.contentWindow.print();
}
function render(){
 const target=desiredTotal();const calculated=fiscalPreview();syncProposals(calculated);renderAdditional(calculated);
 $('[data-total]').textContent=euro(sel.verified?sel.verified.total:calculated.total);
 $('[data-treatment-summary]').textContent=treatmentLabels[sel.treatment].title+' · '+sel.qty+' '+(sel.qty===1?treatmentLabels[sel.treatment].unit:treatmentLabels[sel.treatment].plural)+'\n'+($('[data-vat]').value==='0'?'Medizinisch / steuerfrei (zu prüfen)':'Ästhetisch, inkl. '+$('[data-vat]').value+' % USt.');
 const preview=sel.verified?sel.verified:(calculated.impossible?{...calculated,fee:0,tax:0}:calculated);
 $('[data-fee]').textContent=euro(preview.fee);$('[data-material-total]').textContent=euro(preview.material);$('[data-tax]').textContent=euro(preview.tax);
 for(const [part,key] of [['fee','fee'],['material','material'],['tax','tax']]){
  $('[data-bar-'+part+']').style.width=(preview.total?Math.max(0,100*preview[key]/preview.total):0)+'%';
 }
 if(target===null||target<5000||target>300000){
  setStatus('Betrag eingeben','Bitte einen gültigen Gesamtbetrag in Euro angeben.','error');
 }else if(sel.verified){
  const gap=Math.abs(sel.verified.total-target);
  setStatus(gap===0?'✓ GOÄ-Entwurf rechnerisch geprüft':'Gesamtbetrag weicht ab',
   gap===0?'Positionen wurden serverseitig geprüft. Ärztliche und steuerliche Prüfung bleibt notwendig.':'Die ausgewählten GOÄ-Positionen ergeben '+euro(sel.verified.total)+' statt '+euro(target)+'. Faktoren/Positionen prüfen; keine automatische Anpassung.',''+(gap===0?'ok':'error'));
 }else if(calculated.impossible){
  setStatus('Preis oder Material prüfen','Der Wunschbetrag deckt Material und Mindestsätze nicht oder die Eingabe ist ungültig. Rechnerischer Mindestbetrag: '+euro(calculated.minimum)+'.','error');
 }else{
  const main=calculated.proposals[0],f=calculated.factor, code=treatmentLabels[sel.treatment].code;
  const high=calculated.proposals.some(x=>x.factor>ceiling(x.code));
  const reasonNeeded=calculated.proposals.some(x=>x.factor>threshold(x.code)&&x.factor<=ceiling(x.code));
  const note=' Nr. '+code+' · Faktor '+decimalFactor(f)+'. '+(calculated.illustration?'Material ist ein Referenzwert, kein bestätigter Einkaufspreis. ':'')+'Nur Vorschlag; ärztliche Prüfung erforderlich.';
  if(high)setStatus('Honorarvereinbarung nötig',note+' Vor Behandlung gesondert schriftlich vereinbaren. Speichern nur nach Prüfung des bereits unterzeichneten Dokuments und serverseitiger Berechnung.'+(f>10?' Faktor ungewöhnlich hoch; bitte prüfen.':''),'error');
  else if(reasonNeeded)setStatus('Begründung nötig',note+' Individuelle Begründung dokumentieren.','warning');
  else setStatus('Im Regelrahmen (Vorschau)',note,'ok');
 }
 renderPaper(preview);
 $('[data-material-notice]').hidden=!calculated.materials.some(m=>m.cost>2556);
}
function setMessage(msg,kind='error'){const el=$('[data-goae-feedback]');el.textContent=msg;el.className='mlr-feedback '+kind;}
const saveButton=form.querySelector('.mlr-save');
const previewButton=$('[data-goae-preview]');
const draftRequests=new Map();
function setBusy(){
 const busy=sel.working||sel.quoting;
 saveButton.disabled=busy;
 saveButton.setAttribute('aria-busy',String(busy));
 previewButton.disabled=busy;
}
async function fetchBilling(url, options){
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(), 25000);
 try{
  const response=await fetch(url,{...options,credentials:'same-origin',signal:controller.signal});
  if(response.redirected)return {ok:false,message:'Bitte erneut im Praxismanagement anmelden.'};
  const data=await response.json();
  return {...data,ok:response.ok&&data.ok};
 }finally{clearTimeout(timer);}
}
async function verify(){
 const target=desiredTotal();if(target===null||target<100){setMessage('Zuerst einen gültigen Gesamtbetrag eingeben.');return false;}
 if(!$('#goaePatient').value){setMessage('Patient auswählen.');details.open=true;$('#goaePatient').focus();return false;}
 const date=toISO($('#goaeDateGerman').value);$('#goaeDateIso').value=date;
 if(!date){setMessage('Leistungsdatum bitte als TT.MM.JJJJ eingeben.');details.open=true;$('#goaeDateGerman').focus();return false;}
 const source=linesForServer();if(source.error){setMessage(source.error);details.open=true;return false;}
 if(!$('[data-material]').value.trim()){setMessage('Tatsächlichen Materialwert eingeben (0,00 falls keine Auslage).');details.open=true;return false;}
 if(!source.lines.length){setMessage('Mindestens eine tatsächlich erbrachte Leistung wählen.');return false;}
 const sig=JSON.stringify(source.lines), patientId=$('#goaePatient').value, revision=sel.revision;
 sel.quoting=true;
 setBusy();
 setMessage('GOÄ-Berechnung wird geprüft …','');
 let data;
 try{
  data=await fetchBilling('/verwaltung/api/goae-quote/',{
   method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf.value},
   body:JSON.stringify({lines:source.lines,customer_id:patientId,service_date:date})
  });
 }catch(err){
  setMessage('GOÄ-Berechnung konnte nicht geladen werden. Bitte erneut prüfen.');
  return false;
 }finally{sel.quoting=false;setBusy();}
 const current=linesForServer();
 if(sel.revision!==revision||current.error||JSON.stringify(current.lines)!==sig||desiredTotal()!==target||$('#goaePatient').value!==patientId||toISO($('#goaeDateGerman').value)!==date){setMessage('Eingaben wurden geändert. Bitte erneut prüfen.');return false;}
 if(!data.ok){setMessage(data.message||'GOÄ-Positionen oder Auslagen nicht zulässig.');return false;}
 const total=Number(data.total_cents)||0,fee=(data.items||[]).reduce((sum,x)=>sum+(x.goae_number?x.net_cents:0),0);
 const material=(data.items||[]).reduce((sum,x)=>sum+(!x.goae_number?x.net_cents:0),0);
 const tax=Number(data.tax_cents)||0;
 sel.verified={total,fee,material,tax,items:data.items,lines:source.lines};
 sel.verifiedHash=sig;render();
 const matched=total===target;
 setMessage(matched?'Serverberechnung erfolgreich. GOÄ-Entwurf kann gespeichert werden.':'Rechnerisch geprüft, aber Wunschpreis und GOÄ-Positionen stimmen nicht überein: '+euro(total)+' statt '+euro(target)+'. Bitte Faktoren und Angaben prüfen.',matched?'ok':'error');
 return matched;
}
function syncSlider(){const value=desiredTotal();if(value!==null&&value>=50){$('[data-target-slider]').value=Math.max(50,Math.min(1500,value/100));}}
$$('.mlr-treatment').forEach(b=>b.addEventListener('click',()=>changeTreatment(b.dataset.treatment)));
$('[data-qty-minus]').addEventListener('click',()=>{const old=sel.qty;sel.qty=Math.max(1,sel.qty-1);if(Number($('[data-material-qty]').value)===old)$('[data-material-qty]').value=String(sel.qty);if(sel.injections===treatmentLabels[sel.treatment].injections*old)sel.injections=null;$('[data-qty]').textContent=sel.qty;resetClinicalProposal()});
$('[data-qty-plus]').addEventListener('click',()=>{const old=sel.qty;sel.qty=Math.min(treatmentLabels[sel.treatment].max,sel.qty+1);if(Number($('[data-material-qty]').value)===old)$('[data-material-qty]').value=String(sel.qty);if(sel.injections===treatmentLabels[sel.treatment].injections*old)sel.injections=null;$('[data-qty]').textContent=sel.qty;resetClinicalProposal()});
$('[data-target-input]').addEventListener('input',()=>{syncSlider();resetClinicalProposal()});
$('[data-target-slider]').addEventListener('input',e=>{$('[data-target-input]').value=String(e.target.value);resetClinicalProposal()});
$$('[data-preset]').forEach(b=>b.addEventListener('click',()=>{$('[data-target-input]').value=b.dataset.preset;syncSlider();resetClinicalProposal()}));
$$('[data-material],[data-material-qty],[data-vat],[data-material-confirm],[data-material-receipt],[data-material-description]').forEach(el=>{
 const changed=()=>{if(el.matches('[data-material],[data-material-qty],[data-vat]')){if(el.matches('[data-material],[data-material-qty]')){$('[data-material-confirm]').checked=false;sel.materialsExplicit=true;}resetClinicalProposal();}else resetVerification();};
 el.addEventListener('input',changed);
 el.addEventListener('change',changed);
});
$('#goaePatient').addEventListener('change',()=>{$('[data-agreement-confirm]').checked=false;$('[data-agreement-document]').value='';$('[data-agreement-date]').value='';$('[data-agreement-amount]').value='';for(const line of $$('.mlr-line'))field(line,'clinical_confirmed').checked=false;$('[data-material-confirm]').checked=false;resetVerification()});
$('#goaeDateGerman').addEventListener('input',()=>{$('#goaeDateIso').value='';$('[data-agreement-confirm]').checked=false;for(const line of $$('.mlr-line'))field(line,'clinical_confirmed').checked=false;resetVerification()});
$('[data-native-date]').addEventListener('change',e=>{if(e.target.value)$('#goaeDateGerman').value=fmtDate(e.target.value);resetVerification()});
$('[data-open-calendar]').addEventListener('click',()=>{
 const input=$('[data-native-date]');input.value=toISO($('#goaeDateGerman').value);
 if(typeof input.showPicker==='function')input.showPicker();else{input.focus();input.click()}
});
$('[data-goae-add]').addEventListener('click',()=>{addLine('');sel.clinicalTouched=true;resetVerification()});
previewButton.addEventListener('click',()=>{if(!sel.working&&!sel.quoting)verify();});
$('[data-injection-count]').addEventListener('input',e=>{sel.injections=e.target.value===''?0:Number(e.target.value);resetClinicalProposal()});
$('[data-material-add]').addEventListener('click',addMaterial);
$('[data-diagnosis]').addEventListener('change',()=>{$('[data-diagnosis-custom-wrap]').hidden=$('[data-diagnosis]').value!=='custom';resetVerification()});
$('[data-diagnosis-custom]').addEventListener('input',resetVerification);
$$('[data-invoice-date],[data-due-date]').forEach(x=>x.addEventListener('change',resetVerification));
$('[data-vat]').addEventListener('change',()=>{buildDiagnoses();resetVerification()});
$$('[data-boundary]').forEach(button=>button.addEventListener('click',()=>{
 const cap=Number(button.dataset.boundary);
 for(const input of $$('[data-fixed-code]')){const code=input.dataset.fixedCode,max=cap===2.3?threshold(code):ceiling(code);const old=Number(input.value.replace(',','.'));if(old>max){input.value=String(max).replace('.',',');sel.fixed[code]=input.value;}}
 $('[data-target-input]').value=button.dataset.price;syncSlider();resetClinicalProposal();
}));
$('[data-standard-values]').addEventListener('click',()=>{resetMaterials();buildFixed();sel.injections=null;sel.reasonValues={};sel.reasonSignature='';resetClinicalProposal()});
$('[data-agreement-preview]').addEventListener('click',printAgreement);
$$('[data-agreement-document],[data-agreement-date],[data-agreement-amount],[data-agreement-confirm]').forEach(el=>el.addEventListener('input',()=>{if(!el.matches('[data-agreement-confirm]'))$('[data-agreement-confirm]').checked=false;resetVerification()}));
$('[data-open-details]').addEventListener('click',()=>{details.open=true;details.scrollIntoView({behavior:'smooth',block:'start'})});
$('[data-reset]').addEventListener('click',()=>{
 $('[data-agreement-confirm]').checked=false;$('[data-agreement-document]').value='';$('[data-agreement-date]').value='';$('[data-agreement-amount]').value='';sel.qty=1;sel.injections=null;sel.reasonText='';sel.reasonTreatment=null;sel.clinicalTouched=false;$('[data-qty]').textContent='1';
 $('[data-target-input]').value='260';$('[data-target-slider]').value='260';$('[data-vat]').value='19';buildDiagnoses();$('[data-invoice-date]').value=localISO(new Date());$('[data-due-date]').value='';
 $('[data-material]').value='';$('[data-material-receipt]').value='';$('[data-material-description]').value='';$('[data-material-confirm]').checked=false;
 list.replaceChildren();changeTreatment('hyaluron');setMessage('Alle Beispielwerte zurückgesetzt; Patientendaten bleiben erhalten.','');
});
$('[data-print-simulation]').addEventListener('click',()=>{render();window.print()});
form.addEventListener('submit',async ev=>{
 ev.preventDefault();
 if(sel.working||sel.quoting)return;
 sel.working=true;
 setBusy();
 try{
  const data=linesForServer();
  if(data.error){setMessage(data.error);details.open=true;return;}
  const sig=JSON.stringify(data.lines||[]);
  if(!sel.verified||sel.verifiedHash!==sig||sel.verified.total!==targetOrZero()){
   details.open=true;
   if(!await verify())return;
  }
  if(!form.checkValidity()){details.open=true;form.reportValidity();return;}
  const date=toISO($('#goaeDateGerman').value);
  if(!date){setMessage('Ungültiges Leistungsdatum.');return;}
  $('#goaeDateIso').value=date;
  $('#goaeLinesJson').value=sig;
  $('#goaeTargetCents').value=String(targetOrZero());
  const payload=new FormData(form);
  const signature=JSON.stringify([payload.get('customer_id'),date,sig,payload.get('goae_target_cents')]);
  if(!draftRequests.has(signature))draftRequests.set(signature,crypto.randomUUID());
  payload.set('draft_request_id',draftRequests.get(signature));
  setMessage('GOÄ-Entwurf wird gespeichert …','');
  const url=form.getAttribute('action')||window.location.pathname;
  const result=await fetchBilling(url,{method:'POST',headers:{'Accept':'application/json'},body:payload});
  if(!result.ok){setMessage(result.message||'Der Entwurf konnte nicht gespeichert werden.');return;}
  window.location.assign(result.location);
 }catch(err){
  setMessage('Speicherung konnte nicht bestätigt werden. Bitte mit denselben Angaben erneut versuchen.');
 }finally{sel.working=false;setBusy();}
});
const today=new Date();
$('[data-invoice-date]').value=localISO(today);buildDiagnoses();$('[data-today]').textContent=today.toLocaleDateString('de-DE');
$('#goaeDateGerman').value=today.toLocaleDateString('de-DE',{day:'2-digit',month:'2-digit',year:'numeric'});
changeTreatment('hyaluron');syncSlider();render();
})();
