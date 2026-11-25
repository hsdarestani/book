"""Admin-only contact export; never include clinical data or booking details."""
import csv
import logging

from django.http import HttpResponse, HttpResponseBadRequest
from django.utils import timezone

from .customer_identity import normalize_email
from .models import Customer, SimplyBookClientLink

logger = logging.getLogger(__name__)


def _safe_cell(value):
    """Prevent spreadsheet formula injection, including leading whitespace."""
    value = str(value if value is not None else '')
    stripped = value.lstrip()
    if stripped.startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def customer_csv_export(request):
    mode = request.GET.get('export')
    if mode not in ('all', 'simplybook'):
        return HttpResponseBadRequest('Ungültiger Export.')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = (
        f'attachment; filename="aplus-{mode}-kunden-{timezone.localdate():%Y-%m-%d}.csv"'
    )
    response['Cache-Control'] = 'private, no-store, no-cache, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    response.write('\ufeff')
    writer = csv.writer(response, delimiter=';', lineterminator='\r\n')
    count = 0
    if mode == 'simplybook':
        writer.writerow(['SimplyBook-ID', 'Name', 'E-Mail', 'Telefon', 'Lokale Kunden-ID'])
        rows = SimplyBookClientLink.objects.order_by('external_client_id').values_list(
            'external_client_id', 'source_name', 'source_email', 'source_phone', 'customer_id',
        ).iterator(chunk_size=1000)
        for external_id, name, email, phone, customer_id in rows:
            writer.writerow([_safe_cell(v) for v in (
                external_id, name, email if normalize_email(email) else '', phone, customer_id,
            )])
            count += 1
    else:
        writer.writerow(['Kunden-ID', 'Vorname', 'Nachname', 'E-Mail', 'Telefon'])
        rows = Customer.objects.order_by('last_name', 'first_name', 'pk').values_list(
            'pk', 'first_name', 'last_name', 'email', 'phone',
        ).iterator(chunk_size=1000)
        for customer_id, first, last, email, phone in rows:
            writer.writerow([_safe_cell(v) for v in (
                customer_id, first, last, email if normalize_email(email) else '', phone,
            )])
            count += 1
    logger.info('Customer CSV export user_id=%s scope=%s rows=%s', request.user.pk, mode, count)
    return response
