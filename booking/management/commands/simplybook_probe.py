import json
import os
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError


LOGIN_URL = 'https://user-api.simplybook.me/login'
ADMIN_URL = 'https://user-api.simplybook.me/admin'


class RpcError(RuntimeError):
    pass


def rpc(url, method, params, headers=None, timeout=90):
    payload = json.dumps({
        'jsonrpc': '2.0',
        'method': method,
        'params': params,
        'id': 1,
    }).encode('utf-8')
    request = urllib.request.Request(
        url,
        data=payload,
        headers={'Content-Type': 'application/json', **(headers or {})},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:800]
        raise RpcError(f'HTTP {exc.code} calling {method}: {detail}') from exc
    except urllib.error.URLError as exc:
        raise RpcError(f'Network error calling {method}: {exc}') from exc
    if body.get('error'):
        error = body['error']
        raise RpcError(f"RPC {method} failed: {error.get('code')} {error.get('message')} {error.get('data', '')}")
    return body.get('result')


def shape(value):
    if isinstance(value, dict):
        sample = next(iter(value.values()), None)
        return {
            'type': 'dict',
            'count': len(value),
            'keys': sorted(value.keys())[:25],
            'item_keys': sorted(sample.keys()) if isinstance(sample, dict) else [],
        }
    if isinstance(value, list):
        sample = value[0] if value else None
        return {
            'type': 'list',
            'count': len(value),
            'item_keys': sorted(sample.keys()) if isinstance(sample, dict) else [],
        }
    return {'type': type(value).__name__, 'value_preview': str(value)[:120]}


class Command(BaseCommand):
    help = 'Read-only probe of SimplyBook Admin API for migration planning. Does not write local or remote data.'

    def handle(self, *args, **options):
        company = (os.environ.get('SIMPLYBOOK_COMPANY_LOGIN') or '').strip()
        user = (os.environ.get('SIMPLYBOOK_USER_LOGIN') or '').strip()
        credential = (
            os.environ.get('SIMPLYBOOK_API_USER_KEY')
            or os.environ.get('SIMPLYBOOK_USER_PASSWORD')
            or ''
        ).strip()
        if not company or not user or not credential:
            raise CommandError(
                'Missing SIMPLYBOOK_COMPANY_LOGIN, SIMPLYBOOK_USER_LOGIN and '
                'SIMPLYBOOK_USER_PASSWORD (or SIMPLYBOOK_API_USER_KEY).'
            )

        self.stdout.write('SimplyBook probe: authenticating…')
        try:
            token = rpc(LOGIN_URL, 'getUserToken', [company, user, credential])
        except RpcError as exc:
            raise CommandError(str(exc)) from exc
        if not token:
            raise CommandError('SimplyBook returned an empty user token.')

        headers = {
            'X-Company-Login': company,
            'X-User-Token': token,
        }
        calls = {
            'company': ('getCompanyInfo', []),
            'timezone': ('getCompanyTimezoneOffset', []),
            'services': ('getEventList', [False, True, None, '']),
            'providers': ('getUnitList', [False, True, None, '']),
            'clients': ('getClientList', ['', None]),
            'statuses': ('getStatuses', []),
            'bookings': ('getBookings', [{
                'date_from': '2000-01-01',
                'date_to': '2035-12-31',
                'booking_type': 'all',
                'order': 'date_start_asc',
            }]),
        }

        report = {'authenticated': True, 'company_login': company, 'datasets': {}}
        for label, (method, params) in calls.items():
            try:
                result = rpc(ADMIN_URL, method, params, headers=headers)
                report['datasets'][label] = {'ok': True, **shape(result)}
            except RpcError as exc:
                report['datasets'][label] = {'ok': False, 'error': str(exc)}

        # Probe one provider work calendar for the current month if providers are available.
        try:
            providers = rpc(ADMIN_URL, 'getUnitList', [False, True, None, ''], headers=headers)
            first = providers[0] if isinstance(providers, list) and providers else None
            provider_id = first.get('id') if isinstance(first, dict) else None
            if provider_id:
                from django.utils import timezone
                today = timezone.localdate()
                calendar = rpc(ADMIN_URL, 'getWorkCalendar', [today.year, today.month, int(provider_id)], headers=headers)
                report['datasets']['provider_work_calendar_sample'] = {'ok': True, **shape(calendar)}
        except Exception as exc:  # probe must keep reporting other datasets
            report['datasets']['provider_work_calendar_sample'] = {'ok': False, 'error': str(exc)[:500]}

        self.stdout.write('SIMPLYBOOK_PROBE_JSON=' + json.dumps(report, ensure_ascii=False, sort_keys=True))
        failed = [name for name, data in report['datasets'].items() if not data.get('ok')]
        if failed:
            self.stdout.write(self.style.WARNING('Probe completed with unavailable datasets: ' + ', '.join(failed)))
        else:
            self.stdout.write(self.style.SUCCESS('SimplyBook probe completed successfully.'))
