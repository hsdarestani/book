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
    'wallet': ('A+ Wallet', 'A+ Guthaben der Patienten verwalten'),
    'reviews': ('Google Bewertungen', 'Bewertungsaktivitäten prüfen und dokumentieren'),
    'referrals': ('Empfehlungen', 'Empfehlungen an Freunde im Blick behalten'),
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
        'User-Agent': 'A-Esthetic-Book-Unified-Admin/2.0',
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
def app_management(request, section='wallet'):
    if section not in SECTIONS:
        section = 'wallet'
    if not request.session.get('aplus_app_admin'):
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')

    try:
        if request.method == 'POST':
            action = str(request.POST.get('action') or '')
            if action == 'wallet_adjust':
                customer_id = int(request.POST.get('customer_id'))
                credit_text = str(request.POST.get('credit_delta_eur') or '').replace(',', '.').strip()
                credit_cents = int(round(float(credit_text) * 100)) if credit_text else 0
                if not credit_cents:
                    raise ValueError('Bitte einen Betrag größer oder kleiner als 0 eingeben.')
                _api(request, f'customers/{customer_id}/', method='POST', payload={'credit_delta_cents': credit_cents})
                return _redirect('wallet', 'wallet')
            if action == 'review_verify':
                review_id = int(request.POST.get('review_id'))
                rating_text = str(request.POST.get('rating') or '').strip()
                payload = {'action': 'verify', 'google_review_url': request.POST.get('google_review_url') or ''}
                if rating_text:
                    payload['rating'] = int(rating_text)
                _api(request, f'reviews/{review_id}/', method='POST', payload=payload)
                return _redirect('reviews', 'review')

        query = str(request.GET.get('q') or '').strip()
        if section == 'wallet':
            data = _api(request, 'customers/', query={'q': query})
        elif section == 'reviews':
            data = _api(request, 'reviews/')
        else:
            data = _api(request, 'referrals/')

        title, subtitle = SECTIONS[section]
        return render(request, 'booking/app_management.html', {
            'section': section,
            'section_title': title,
            'section_subtitle': subtitle,
            'sections': SECTIONS,
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
            'data': {},
            'error': str(exc),
        }, status=502)
