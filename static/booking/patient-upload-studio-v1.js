/* A+ Esthetic patient archive - additive multi-attachment chooser. */
(()=>{'use strict';
 const MAX_FILES=12;
 const ALLOWED=new Set(['.pdf','.jpg','.jpeg','.png','.webp','.heic','.heif','.doc','.docx','.xls','.xlsx','.txt','.rtf','.csv']);
 const size=n=>n<1024?String(n)+' B':n<1048576?Math.ceil(n/1024)+' KB':(n/1048576).toFixed(1).replace('.',',')+' MB';
 function init(form){
   if(form.dataset.uploadStudioReady)return;
   form.dataset.uploadStudioReady='1';
   const input=form.querySelector('input[data-patient-file]'),list=form.querySelector('[data-upload-list]'),counter=form.querySelector('[data-upload-count]'),error=form.querySelector('[data-upload-error]');
   if(!input||!list)return;
   let chosen=[];
   const urls=[];
   const maxBytes=Number(form.dataset.maxFileMb||20)*1024*1024;
   const signature=f=>[f.name,f.size,f.lastModified].join('|');
   function errorText(message){error.textContent=message||'';error.hidden=!message;}
   function sync(){
     try{const dt=new DataTransfer();chosen.forEach(f=>dt.items.add(f));input.files=dt.files;return true;}catch(_){return false;}
   }
   function render(){
     urls.splice(0).forEach(url=>URL.revokeObjectURL(url));
     list.replaceChildren();
     counter.textContent=chosen.length?chosen.length+' von '+MAX_FILES+' Dateien ausgewählt':'Bis zu '+MAX_FILES+' Dateien · Fotos, PDF und Dokumente';
     list.hidden=!chosen.length;
     for(const [index,file] of chosen.entries()){
       const item=document.createElement('li');item.className='patient-upload-item';
       const art=document.createElement('span');art.className='patient-upload-thumb';
       if(file.type.startsWith('image/')&&typeof URL.createObjectURL==='function'){
         const url=URL.createObjectURL(file);urls.push(url);const img=document.createElement('img');img.src=url;img.alt='';art.append(img);
       }else{art.textContent=(file.name.split('.').pop()||'FILE').slice(0,5).toUpperCase();}
       const meta=document.createElement('span');meta.className='patient-upload-info';
       const name=document.createElement('strong');name.textContent=file.name;
       const details=document.createElement('small');details.textContent=size(file.size)+' · Bereit zum Speichern';
       meta.append(name,details);
       const remove=document.createElement('button');remove.type='button';remove.className='patient-upload-remove';remove.setAttribute('aria-label',file.name+' entfernen');remove.textContent='×';
       remove.addEventListener('click',()=>{chosen.splice(index,1);sync();errorText('');render()});
       item.append(art,meta,remove);list.append(item);
     }
   }
   function add(files){
     const incoming=Array.from(files||[]);if(!incoming.length)return;
     const merged=[...chosen],keys=new Set(chosen.map(signature));
     for(const f of incoming){
       const extension='.'+(f.name.split('.').pop()||'').toLowerCase();
       if(!ALLOWED.has(extension)){errorText('Dateityp nicht erlaubt: '+f.name);sync();return;}
       if(!f.size||f.size>maxBytes){errorText('Datei zu groß oder leer: '+f.name+' (max. '+form.dataset.maxFileMb+' MB je Datei)');sync();return;}
       if(keys.has(signature(f)))continue;
       if(merged.length>=MAX_FILES){errorText('Maximal 12 Dateien gleichzeitig. Entferne zuerst eine Datei.');sync();return;}
       merged.push(f);keys.add(signature(f));
     }
     chosen=merged;
     if(!sync()){chosen=incoming;errorText('Mehrfachauswahl konnte nicht zusammengeführt werden. Bitte Dateien in einem Schritt auswählen.');}
     else errorText('');
     render();
   }
   input.addEventListener('change',()=>add(input.files));
   const zone=form.querySelector('[data-upload-drop]');
   if(zone){
     zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('is-drag-over')});
     zone.addEventListener('dragleave',()=>zone.classList.remove('is-drag-over'));
     zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('is-drag-over');add(e.dataTransfer?.files)});
   }
   form.addEventListener('submit',e=>{
     if(!sync()&&chosen.length){e.preventDefault();errorText('Dateiauswahl fehlgeschlagen. Bitte Dateien erneut auswählen.');return;}
     const save=form.querySelector('[data-upload-submit]');
     if(save&&!e.defaultPrevented){save.disabled=true;save.textContent='Wird sicher gespeichert …';}
   });
   form.addEventListener('reset',()=>{chosen=[];errorText('');setTimeout(render,0)});
   window.addEventListener('pagehide',()=>urls.splice(0).forEach(url=>URL.revokeObjectURL(url)),{once:true});
   render();
 }
 function boot(){document.querySelectorAll('form.patient-upload-studio').forEach(init)}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
