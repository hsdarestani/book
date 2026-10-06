(() => {
  const modal=document.querySelector('[data-billing-customer-modal]');
  const customerInput=document.querySelector('[data-billing-customer-input]');
  const customerName=document.querySelector('[data-billing-customer-name]');
  const customerMeta=document.querySelector('[data-billing-customer-meta]');
  const customerSearch=document.querySelector('[data-billing-customer-search]');
  const customerError=document.querySelector('[data-billing-customer-error]');
  const noResults=document.querySelector('[data-billing-customer-no-results]');
  const form=document.querySelector('[data-billing-create-form]');
  const dateNative=document.querySelector('[data-billing-date-native]');
  const dateValue=document.querySelector('[data-billing-date-value]');
  const dateLabel=document.querySelector('[data-billing-date-label]');
  const dateError=document.querySelector('[data-billing-date-error]');

  function openModal(){
    if(!modal)return;
    modal.hidden=false;
    document.documentElement.classList.add('billing-modal-open');
    document.body.classList.add('billing-modal-open');
    setTimeout(()=>customerSearch?.focus(),80);
  }
  function closeModal(){
    if(!modal)return;
    modal.hidden=true;
    document.documentElement.classList.remove('billing-modal-open');
    document.body.classList.remove('billing-modal-open');
    if(customerSearch){customerSearch.value='';customerSearch.dispatchEvent(new Event('input'));}
  }

  document.querySelectorAll('[data-billing-customer-open]').forEach(x=>x.addEventListener('click',openModal));
  document.querySelectorAll('[data-billing-customer-close]').forEach(x=>x.addEventListener('click',closeModal));

  document.querySelectorAll('[data-billing-customer-option]').forEach(button=>{
    button.addEventListener('click',()=>{
      if(customerInput)customerInput.value=button.dataset.customerId||'';
      if(customerName)customerName.textContent=button.dataset.customerName||'Kunde';
      if(customerMeta)customerMeta.textContent=button.dataset.customerEmail||'';
      if(customerError)customerError.hidden=true;
      document.querySelectorAll('[data-billing-customer-option]').forEach(item=>item.classList.remove('is-selected'));
      button.classList.add('is-selected');
      closeModal();
    });
  });

  customerSearch?.addEventListener('input',()=>{
    const q=customerSearch.value.trim().toLocaleLowerCase('de-DE');
    let visible=0;
    document.querySelectorAll('[data-billing-customer-option]').forEach(button=>{
      const hay=(button.dataset.customerSearch||'').toLocaleLowerCase('de-DE');
      const show=!q||hay.includes(q);
      button.hidden=!show;
      if(show)visible+=1;
    });
    if(noResults)noResults.hidden=visible!==0;
  });

  function deDate(iso){
    if(!iso||!/^\d{4}-\d{2}-\d{2}$/.test(iso))return'';
    const [y,m,d]=iso.split('-');
    return `${d}.${m}.${y}`;
  }
  dateNative?.addEventListener('change',()=>{
    const formatted=deDate(dateNative.value);
    if(dateValue)dateValue.value=formatted;
    if(dateLabel)dateLabel.textContent=formatted||'TT.MM.JJJJ';
    if(dateError)dateError.hidden=Boolean(formatted);
  });

  form?.addEventListener('submit',event=>{
    let valid=true;
    if(!customerInput?.value){if(customerError)customerError.hidden=false;valid=false;}
    if(!dateValue?.value){if(dateError)dateError.hidden=false;valid=false;}
    if(!valid){
      event.preventDefault();
      form.querySelector('.billing-field-error:not([hidden])')?.scrollIntoView({behavior:'smooth',block:'center'});
    }
  });
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&modal&&!modal.hidden)closeModal();});
})();