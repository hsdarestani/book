import logging
import os
import re
from copy import copy
from urllib.error import HTTPError

from django.utils import timezone
from booking.clinical_time import clinic_localtime
from booking.models import Appointment
from booking.simplybook_outbound import (
    ARIANE, SERVICE_MAP, UNIT_ID, _additional_answers, _contact_matches, as_bool, session,
)
from booking.management.commands.sync_simplybook_notes import AUTH_URL, _request_json
from django.core.management.base import CommandError

logging.disable(logging.CRITICAL)
stage = 'identify'
try:
    rows = list(Appointment.objects.select_related('customer', 'staff', 'service').filter(
        idempotency_key__startswith='qa-sb-', customer__first_name='Synthetic Book',
        customer__email__endswith='@example.com', customer__phone='+12025550141',
        staff__display_name=ARIANE, source='app', service__slug='aesthetische-erstberatung',
    ))
    if len(rows) != 1:
        raise RuntimeError('ambiguous_local_fixture')
    item = rows[0]
    tag = item.idempotency_key.removeprefix('qa-sb-')
    if not re.fullmatch('[0-9a-f]{32}', tag):
        raise RuntimeError('fixture_key_mismatch')
    email = 'esthetic-book-qa-' + tag + '@example.com'
    if item.customer.email != email or item.customer.last_name != 'QA '+tag:
        raise RuntimeError('fixture_identity_mismatch')
    call = session()
    event = SERVICE_MAP[item.service.slug][0]
    day = clinic_localtime(item.starts_at).date().isoformat()
    stage = 'verify_booking_absence'
    cid = int(item.simplybook_client_id)
    remote_rows = call('getBookings', [{'date_from': day, 'date_to': day, 'booking_type': 'all'}])
    if not isinstance(remote_rows, list):
        raise RuntimeError('fixture_booking_list_unconfirmed')
    if any(str(row.get('client_id')) == str(cid) for row in remote_rows):
        raise RuntimeError('fixture_source_booking_requires_targeted_check')
    stage = 'delete_fixture_client'
    company = os.environ['SIMPLYBOOK_COMPANY_LOGIN']
    auth = _request_json(AUTH_URL, method='POST', payload={'company': company,
        'login': os.environ['SIMPLYBOOK_USER_LOGIN'], 'password': os.environ['SIMPLYBOOK_USER_PASSWORD']}, timeout=15)
    headers = {'X-Company-Login': company, 'X-Token': auth['token']}
    url = 'https://user-api-v2.simplybook.me/admin/clients/' + str(cid)
    def client():
        try:
            return _request_json(url, headers=headers, timeout=15)
        except CommandError as exc:
            if re.match(r'SimplyBook notes HTTP 404\b', str(exc)):
                return None
            raise
    remote = client()
    if remote is not None:
        assert isinstance(remote, dict) and int(remote['id']) == cid
        if not as_bool(remote.get('is_deleted')):
            assert _contact_matches(remote, item.customer)
            _request_json(url, method='DELETE', headers=headers, timeout=15)
        result = client()
        assert result is None or (int(result['id']) == cid and as_bool(result.get('is_deleted')))
    assert not [x for x in call('getClientList', [email, None]) if _contact_matches(x, item.customer)]
    stage = 'delete_local_fixture'
    customer = item.customer
    item.delete()
    customer.delete()
    print('SYNTHETIC_SOURCE_AND_LOCAL_CLEANUP_VERIFIED=true', flush=True)
    stage = 'read_capabilities'
    print('ADDITIONAL_FIELDS_PLUGIN=' + str(as_bool(call('isPluginActivated', ['event_field']))))
    for slug, (event, _) in SERVICE_MAP.items():
        fields = call('getAdditionalFields', [event])
        configured = copy(item)
        configured.service = copy(item.service)
        configured.service.slug = slug
        try:
            answers = _additional_answers(call, configured, event)
        except Exception:
            answers = {}
        for field in fields:
            label = re.sub(r'[^a-z0-9äöüß ?()-]', '', str(field.get('title', '')).casefold())[:95]
            flags = ','.join(sorted(k for k in field if 'required' in k or 'mandat' in k or 'optional' in k))
            print('FIELD_CONTRACT=' + str(event) + ':' + label + ':' + flags + ':' + str(bool(answers.get(field.get('name')))))
    date = clinic_localtime(item.starts_at).date()
    days = call('getUnitWorkdayInfo', [day, day, UNIT_ID])
    calendar = call('getWorkCalendar', [date.year, date.month, {'unit_group_id': UNIT_ID}])
    sample = calendar.get(day) if isinstance(calendar, dict) else None
    print('ARIANE_WORKING_HOURS_DATE_READ=' + str(bool(days and sample)))
    if isinstance(sample, dict):
        print('WORK_CALENDAR_DAY_SCHEMA=' + ','.join(sorted(k for k in sample if k in {'from','to','is_day_off','breaktime','id','is_special_day','is_special','date'})))
except Exception as exc:
    allowed = ('ambiguous_local_fixture','fixture_key_mismatch','fixture_identity_mismatch','fixture_booking_list_unconfirmed','fixture_source_booking_requires_targeted_check')
    safe = str(exc) if str(exc) in allowed else type(exc).__name__
    raise SystemExit('CLEANUP_OR_PROBE_NOT_CONFIRMED=' + stage + ':' + safe) from None
