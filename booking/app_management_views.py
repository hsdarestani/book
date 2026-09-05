import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods


AESTHETIC_ADMIN_API = 'https://esthetic.smarbiz.sbs/api/mobile/admin'
SECTIONS = {
    'club': ('Customer Club', 'Mitglieder, Guthaben und Mitgliedsstatus'),
    'packages': ('Pakete', 'Aktive und vergangene Behandlungspakete'),
    'rewards': ('Rewards', 'Einlösungen bearbeiten und abschließen'),
    'notifications': ('Push & Mitteilungen', 'Nachrichten an einzelne oder alle Mitglieder senden'),
    'referrals': ('Empfehlungen', 'Referral-Codes, Status und Prämien'),
    'modules': ('App-Module', 'Sichtbarkeit und Verfügbarkeit der App-Funktionen'),
    'devices': ('Konten & Geräte', 'Registrierte App-Geräte und Versionen'),
}


def _authorization(request):
    value = str(request.session.get('aplus_admin_authorization') or '').strip()
    return value if value.startswith('Bearer ') else ''


def _api(request, endpoint, method='GET', payload=None, query=None):
    authorization = _authorization(request)
    if not authorization:
        raise PermissionError('A+ Admin-Sitzung fehlt')
    url = f"{AESTHETIC_ADMIN_API}/{endpoint.lstrip('/')}"
    if query:
        encoded = urlencode({key: value for key, value in query.items() if value not in (None, '')})
        if encoded:
            url += f'?{encoded}'
    body = None
    headers = {
        'Authorization': authorization,
        'Accept': 'application/json',
        'User-Agent': 'A-Esthetic-Book-Unified-Admin/1.0',
    }
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    remote = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(remote, timeout=20) as response:
            raw = response.read().decode('utf-8')
            status = response.status
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', 'replace')
        status = exc.code
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f'A+ API nicht erreichbar: {exc}') from exc
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError('Ungültige Antwort der A+ API') from exc
    if status in {401, 403}:
        request.session.pop('aplus_admin_authorization', None)
        raise PermissionError(data.get('error') or 'Admin-Sitzung abgelaufen')
    if status >= 400 or not data.get('ok', False):
        raise RuntimeError(data.get('error') or f'A+ API Fehler {status}')
    return data


def _redirect(section, notice='saved'):
    suffix = f'?notice={notice}' if notice else ''
    return redirect(f'/verwaltung/app/{section}/{suffix}')


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def app_management(request, section='club'):
    if section not in SECTIONS:
        section = 'club'
    if not request.session.get('aplus_app_admin'):
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')

    try:
        if request.method == 'POST':
            action = str(request.POST.get('action') or '')
            if action == 'customer_adjust':
                customer_id = int(request.POST.get('customer_id'))
                credit_text = str(request.POST.get('credit_delta_eur') or '').replace(',', '.').strip()
                credit_cents = int(round(float(credit_text) * 100)) if credit_text else 0
                _api(request, f'customers/{customer_id}/', method='POST', payload={
                    'member_status': request.POST.get('member_status') or '',
                    'coin_delta': int(request.POST.get('coin_delta') or 0),
                    'credit_delta_cents': credit_cents,
                })
                return _redirect('club', 'customer')
            if action == 'reward_action':
                redemption_id = int(request.POST.get('redemption_id'))
                _api(request, f'rewards/{redemption_id}/', method='POST', payload={
                    'action': request.POST.get('reward_action'),
                    'note': request.POST.get('note') or '',
                })
                return _redirect('rewards', 'reward')
            if action == 'send_notification':
                all_customers = request.POST.get('audience') == 'all'
                payload = {
                    'all_customers': all_customers,
                    'title': request.POST.get('title') or '',
                    'body': request.POST.get('body') or '',
                    'category': request.POST.get('category') or 'general',
                    'deeplink': request.POST.get('deeplink') or '',
                }
                if not all_customers:
                    payload['user_id'] = int(request.POST.get('user_id'))
                result = _api(request, 'notifications/', method='POST', payload=payload)
                return _redirect('notifications', f"sent-{result.get('recipients', 0)}")
            if action == 'module_update':
                key = str(request.POST.get('key') or '')
                _api(request, f'modules/{key}/', method='POST', payload={
                    'enabled': request.POST.get('enabled') == 'on',
                    'customer_visible': request.POST.get('customer_visible') == 'on',
                })
                return _redirect('modules', 'module')
            if action == 'device_toggle':
                _api(request, 'devices/', method='POST', payload={
                    'device_id': int(request.POST.get('device_id')),
                    'enabled': request.POST.get('enabled') == '1',
                })
                return _redirect('devices', 'device')

        overview = _api(request, '')
        data = {}
        query = str(request.GET.get('q') or '').strip()
        if section == 'club':
            data = _api(request, 'customers/', query={'q': query})
        elif section == 'packages':
            data = _api(request, 'packages/', query={'status': request.GET.get('status') or ''})
        elif section == 'rewards':
            data = _api(request, 'rewards/')
        elif section == 'notifications':
            data = _api(request, 'notifications/history/')
            data['customers'] = _api(request, 'customers/').get('customers', [])
        elif section == 'referrals':
            data = _api(request, 'referrals/')
        elif section == 'modules':
            data = {'modules': overview.get('modules', [])}
        elif section == 'devices':
            data = _api(request, 'devices/')

        title, subtitle = SECTIONS[section]
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': title,
            'section_subtitle': subtitle,
            'sections': SECTIONS,
            'overview': overview,
            'data': data,
            'query': query,
            'notice': request.GET.get('notice') or '',
        })
    except PermissionError as exc:
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'overview': {},
            'data': {},
            'error': str(exc),
            'needs_reauth': True,
        }, status=403)
    except (RuntimeError, ValueError, TypeError) as exc:
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': SECTIONS[section][0],
            'section_subtitle': SECTIONS[section][1],
            'sections': SECTIONS,
            'overview': {},
            'data': {},
            'error': str(exc),
        }, status=502)