(() => {
 'use strict';
 const panel = document.querySelector('[data-goae-assistant]');
 const calculator = document.querySelector('[data-mlr]');
 if (!panel || !calculator) return;
 const form = panel.querySelector('[data-chat-form]');
 const input = form.querySelector('textarea');
 const submit = form.querySelector('[type="submit"]');
 const log = panel.querySelector('[data-chat-log]');
 const csrf = calculator.querySelector('[name="csrfmiddlewaretoken"]').value;
 const treatmentAliases = {
  botox: /\b(?:botox|botulinum(?:toxin)?)\b/i,
  hyaluron: /\bhyaluron(?:säure)?\b/i,
  prp: /\b(?:prp|eigenblut)\b/i,
  lipolysis: /\b(?:injektions)?lipolyse\b/i,
  laser: /\blaser(?:[- ]haarentfernung)?\b/i,
  rf: /\b(?:rf[- ]?)?microneedling\b/i,
  skinbooster: /\bskinbooster\b/i,
  infusion: /\binfusion(?:stherapie)?\b/i,
  consultation: /\b(?:erst)?beratung\b/i,
  followup: /\bkontroll(?:termin|e)\b/i,
  body: /\bbody[- ]contouring\b/i,
 };
 const topics = {
  analog: /analog|gleichwertig/i,
  factor: /faktor|steigerung|begründ|honorarvereinbarung|höchstsatz/i,
  material: /material|auslage|beleg/i,
  tax: /steuer|ust|mwst/i,
  total: /wunschbetrag|gesamt|abweichung|endbetrag/i,
  entry: /anfangen|beginn|ausfüll|speicher|entwurf|rechnung|datum|patient/i,
 };
 const amount = '(\\d{1,4}(?:[,.]\\d{1,2})?)';
 const currency = '(?:€|euro)';
 const gross = new RegExp(amount+'\\s*'+currency+'\\s*(?:brutto|gesamt)|(?:brutto|gesamt(?:betrag)?|wunschbetrag)\\s*:?\\s*'+amount, 'i');
 const material = new RegExp(amount+'\\s*'+currency+'\\s*(?:material|auslagen?)|(?:material|auslagen?)\\s*:?\\s*'+amount, 'i');

 function message(text) {
  const el = document.createElement('p');
  el.textContent = text;
  log.append(el);
  if (log.children.length > 12) log.firstElementChild.remove();
  log.scrollTop = log.scrollHeight;
  return el;
 }

 function propose(text) {
  const treatmentKeys = Object.keys(treatmentAliases).filter(key => treatmentAliases[key].test(text));
  if (treatmentKeys.length > 1) return 'Bitte jeweils nur eine Behandlung angeben.';
  const patch = {};
  const labels = [];
  if (treatmentKeys.length) {
   const card = calculator.querySelector('[data-treatment="'+treatmentKeys[0]+'"]');
   if (!card) return 'Diese Behandlung ist in der Auswahlliste nicht verfügbar.';
   patch.treatment = card.dataset.treatment;
   labels.push(card.dataset.treatmentTitle);
  }
  const quantity = /\b(\d{1,2})\s*(?:zonen?|spritzen?|kits?|ampullen?)\b/i.exec(text)?.[1];
  if (quantity !== undefined) {
   patch.quantity = Number(quantity);
   labels.push(quantity+' Einheiten');
  }
  for (const [key, expression, label] of [['total', gross, 'Wunschbetrag'], ['material', material, 'Material netto/Stk.']]) {
   const match = expression.exec(text);
   if (!match) continue;
   const value = (match[1] || match[2]).replace('.', ',');
   patch[key] = value;
   labels.push(label+' '+value+' €');
  }
  const date = /\b(?:am\s+|behandlungsdatum\s*:?\s*|leistungsdatum\s*:?\s*)(\d{2}\.\d{2}\.\d{4})\b/i.exec(text)?.[1];
  if (date) {
   patch.date = date;
   labels.push('Behandlungsdatum '+date);
  }
  if (!labels.length) return '';
  const summary = message(labels.join(' · '));
  const apply = document.createElement('button');
  apply.type = 'button';
  apply.textContent = 'In Formular übernehmen';
  apply.addEventListener('click', () => {
   const event = new CustomEvent('goae:apply', {detail: patch, cancelable: true});
   if (!calculator.dispatchEvent(event)) {
    message(event.detail.error || 'Die Berechnung läuft. Bitte gleich erneut versuchen.');
    return;
   }
   for (const button of log.querySelectorAll('button')) button.remove();
   message('Übernommen. Prüfen Sie die Angaben im Formular.');
  });
  summary.append(document.createElement('br'), apply);
  return null;
 }

 async function ask(topic, label) {
  if (submit.disabled) return;
  submit.disabled = true;
  const answer = message(label+' · Antwort wird geladen …');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 9000);
  try {
   const response = await fetch(panel.dataset.url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
    body: JSON.stringify({topic}),
    signal: controller.signal,
   });
   const result = await response.json().catch(() => ({}));
   answer.textContent = response.ok && result.ok
    ? (result.ai ? 'KI-Hilfe · ' : 'GOÄ-Hilfe · ')+result.answer
    : result.message || 'Sitzung oder Verbindung prüfen und erneut versuchen.';
  } catch {
   answer.textContent = 'Assistent gerade nicht erreichbar. Die Eingaben im Formular bleiben erhalten.';
  } finally {
   clearTimeout(timer);
   submit.disabled = false;
  }
 }
 for (const button of panel.querySelectorAll('[data-topic]')) {
  button.addEventListener('click', () => ask(button.dataset.topic, button.textContent));
 }
 form.addEventListener('submit', event => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || submit.disabled) return;
  input.value = '';
  if (!text.includes('?') || /übernehm|eintrag|ausfüll/i.test(text)) {
   const result = propose(text);
   if (result === null) return;
   if (result) { message(result); return; }
  }
  const topic = Object.keys(topics).find(key => topics[key].test(text));
  if (topic) {
   const button = panel.querySelector('[data-topic="'+topic+'"]');
   ask(topic, button.textContent);
  } else {
   message('Bitte ein Thema auswählen oder Angaben wie „Botox, 2 Zonen, 300 € gesamt, 0 € Material“ eingeben.');
  }
 });
})();
