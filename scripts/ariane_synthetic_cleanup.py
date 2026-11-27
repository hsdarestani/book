import logging
import os
import re
from django.core.management.base import CommandError
from django.db import transaction
from booking.models import Customer, SimplyBookClientLink
from booking.simplybook_outbound import _contact_matches, as_bool, session
from booking.management.commands.sync_simplybook_notes import AUTH_URL, _request_json

logging.disable(logging.CRITICAL)
stage = 'identify'
try:
    rows = list(Customer.objects.filter(
        first_name='Synthetic Book', email__startswith='esthetic-book-qa-',
        email__endswith='@example.com', phone='+12025550141',
    ))
    assert len(rows) == 1
    customer = rows[0]
    tag = customer.email.removeprefix('esthetic-book-qa-').removesuffix('@example.com')
    assert re.fullmatch('[0-9a-f]{32}', tag) and customer.last_name == 'QA '+tag
    assert not customer.appointments.exists()
    link = SimplyBookClientLink.objects.get(customer=customer)
    cid = int(link.external_client_id)
    assert not [row for row in session()('getClientList', [customer.email, None]) if _contact_matches(row, customer)]
    stage = 'verify_vendor_tombstone'
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    fixture_rest_auth = _request_json(AUTH_URL, method='POST', payload={'company': company,
        'login': os.environ['SIMPLYBOOK_USER_LOGIN'], 'password': os.environ['SIMPLYBOOK_USER_PASSWORD']}, timeout=15)
    headers = {'X-Company-Login': company, 'X-Token': fixture_rest_auth['token']}
    try:
        remote = _request_json('https://user-api-v2.simplybook.me/admin/clients/' + str(cid), headers=headers, timeout=15)
    except CommandError as exc:
        if not re.match(r'SimplyBook notes HTTP 404\b', str(exc)):
            raise
    else:
        assert int(remote['id']) == cid and as_bool(remote.get('is_deleted'))
    stage = 'remove_verified_local_fixture'
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        assert not customer.appointments.exists()
        SimplyBookClientLink.objects.get(pk=link.pk, customer=customer, external_client_id=str(cid)).delete()
        customer.delete()
    print('SYNTHETIC_SOURCE_AND_LOCAL_CLEANUP_VERIFIED=true', flush=True)
except Exception as exc:
    raise SystemExit('CLEANUP_NOT_CONFIRMED=' + stage + ':' + type(exc).__name__) from None
