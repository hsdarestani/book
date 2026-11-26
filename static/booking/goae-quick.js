(() => {
  const form = document.querySelector('[data-goae-quick]');
  if (!form) return;
  const status = form.querySelector('[data-quick-status]');
  const results = form.querySelector('[data-quick-results]');
  const link = form.querySelector('[data-quick-pdf]');
  const quote = form.querySelector('[data-quick-quote]');
  const submit = form.querySelector('[type="submit"]');
  const euro = new Intl.NumberFormat('de-DE', {style: 'currency', currency: 'EUR'});
  const savedRequests = new Map();
  let revision = 0;

  function showError(field, message) {
    status.textContent = message;
    if (!field) return;
    field.closest('details')?.setAttribute('open', '');
    field.setAttribute('aria-invalid', 'true');
    field.scrollIntoView({block: 'center'});
    field.focus({preventScroll: true});
  }

  function invalidate() {
    revision += 1;
    form.querySelectorAll('[aria-invalid]').forEach(field => field.removeAttribute('aria-invalid'));
    results.hidden = true;
    link.hidden = true;
    status.textContent = '';
  }

  function desiredCents(value) {
    const match = /^([0-9]{1,7})(?:[.,]([0-9]{1,2}))?$/.exec(value.trim());
    if (!match) return null;
    return Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0'));
  }

  function show(data, desired) {
    if (data.requires_approval) {
      status.textContent = 'Unvollständiger Entwurf gespeichert. Behandlungsvorlage benötigt Freigabe.';
      return;
    }
    results.hidden = false;
    results.querySelector('[data-quick-total]').textContent = euro.format(data.total_cents / 100);
    const list = results.querySelector('[data-quick-lines]');
    const positions = (data.items || []).map(item => {
      const row = document.createElement('li');
      const label = item.number ? item.number + ' · ' + item.description : item.description;
      row.textContent = label + ' · ' + euro.format(item.gross_cents / 100);
      return row;
    });
    list.replaceChildren(...positions);
    list.hidden = !positions.length;
    const difference = desired === null || data.total_cents === desired ? '' :
      ' Der Vorlagenbetrag weicht vom Wunschbetrag ' + euro.format(desired / 100) + ' ab.';
    status.textContent = (data.invoice_id ? 'Entwurf gespeichert.' : 'Vorlagenbetrag berechnet.') + difference;
  }

  async function run(operation) {
    if (submit.disabled) return;
    const invalid = [...form.elements].find(field => field.willValidate && !field.validity.valid);
    if (invalid) return showError(invalid, invalid.validationMessage);
    const fields = new FormData(form);
    const amount = fields.get('desired').trim();
    const desired = amount ? desiredCents(amount) : null;
    if (amount && (desired === null || desired > 100000000)) {
      return showError(form.elements.desired, 'Bitte einen gültigen Betrag mit höchstens zwei Nachkommastellen eingeben.');
    }
    const treatment = form.elements.treatment.selectedOptions[0];
    if (operation === 'quote' && !treatment.dataset.version) {
      return showError(form.elements.treatment, 'Diese Behandlung benötigt eine freigegebene GOÄ-Vorlage. Ein unvollständiger Entwurf kann gespeichert werden.');
    }
    const data = {
      customer_id: fields.get('customer_id'),
      service_date: fields.get('service_date'),
      quick_invoice: {
        treatment: treatment.value,
        version: treatment.dataset.version,
        quantity: Number(fields.get('quantity')),
        desired_cents: desired
      },
      book_preview: {invoice_date: fields.get('invoice_date'), due_date: fields.get('due_date')}
    };
    if (operation === 'draft') {
      const key = JSON.stringify(data);
      if (!savedRequests.has(key)) savedRequests.set(key, crypto.randomUUID());
      data.draft_request_id = savedRequests.get(key);
    }
    const submittedRevision = revision;
    quote.disabled = submit.disabled = true;
    status.textContent = operation === 'draft' ? 'Entwurf wird gespeichert …' : 'Vorlage wird berechnet …';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(form.action, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': fields.get('csrfmiddlewaretoken')},
        body: JSON.stringify({...data, operation}),
        signal: controller.signal
      });
      const result = await response.json();
      if (revision !== submittedRevision) return;
      if (!response.ok || !result.ok) {
        status.textContent = result.message || 'Die Schnellrechnung konnte nicht verarbeitet werden.';
        return;
      }
      show(result, desired);
      if (Number.isSafeInteger(result.invoice_id) && result.invoice_id > 0) {
        link.href = '/verwaltung/app/invoices/' + result.invoice_id + '/pdf/';
        link.hidden = false;
      }
    } catch {
      if (revision === submittedRevision) status.textContent = 'Vorgang nicht bestätigt. Bitte erneut versuchen.';
    } finally {
      clearTimeout(timeout);
      quote.disabled = submit.disabled = false;
    }
  }

  form.noValidate = true;
  form.addEventListener('change', invalidate);
  form.addEventListener('input', invalidate);
  quote.addEventListener('click', () => run('quote'));
  form.addEventListener('submit', event => {
    event.preventDefault();
    run('draft');
  });
})();
