import logging
import os
import re
import runpy
import sys

import django

sys.path.insert(0, os.getcwd())
django.setup()
from booking.management.commands.sync_simplybook_notes import AUTH_URL, _request_json

logging.disable(logging.CRITICAL)
try:
    fixture_rest_auth = _request_json(AUTH_URL, method='POST', payload={
        'company': os.environ['SIMPLYBOOK_COMPANY_LOGIN'],
        'login': os.environ['SIMPLYBOOK_USER_LOGIN'],
        'password': os.environ['SIMPLYBOOK_USER_PASSWORD'],
    }, timeout=25)
    if not fixture_rest_auth.get('token'):
        raise RuntimeError('missing_token')
except Exception as exc:
    match = re.search(r'HTTP (\d{3})', str(exc))
    raise SystemExit('SHARED_REST_AUTH_FAILED=' + type(exc).__name__ + ':' + (match.group(1) if match else 'network')
                     + (':rate_limited' if 'too many attempts' in str(exc).lower() else '')) from None

failed = False
for path in sys.argv[1:]:
    try:
        runpy.run_path(path, init_globals={'fixture_rest_auth': fixture_rest_auth})
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, flush=True)
        failed = True
if failed:
    raise SystemExit(1)
