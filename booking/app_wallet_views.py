from urllib.parse import urlencode

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from . import app_management_views


def _wallet_redirect(**params):
    clean = {key: value for key, value in params.items() if value not in (None, '')}
    suffix = f"?{urlencode(clean)}" if clean else ''
    return redirect(f'/verwaltung/app/wallet/{suffix}')


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def app_wallet_management(request):
    if not request.session.get('aplus_app_admin'):
        return HttpResponseForbidden('A+ App Management ist nur über eine bestätigte A+ Admin-Sitzung verfügbar.')

    try:
        if request.method == 'POST':
            action = str(request.POST.get('action') or '').strip()
            if action == 'wallet_scan':
                token = str(request.POST.get('qr_token') or '').strip()
                if not token:
                    raise ValueError('Bitte einen QR-Code scannen oder die Karten-ID eingeben.')
                result = app_management_views._api(
                    request,
                    'wallet/lookup/',
                    method='POST',
                    payload={'qr_token': token},
                )
                customer = result.get('customer') or {}
                query = str(customer.get('email') or customer.get('member_number') or '').strip()
                if not query:
                    raise ValueError('Die gescannte A+ Karte konnte keinem Patienten zugeordnet werden.')
                return _wallet_redirect(q=query, scan='1')

            if action == 'wallet_adjust':
                customer_id = int(request.POST.get('customer_id'))
                credit_text = str(request.POST.get('credit_delta_eur') or '').replace(',', '.').strip()
                credit_cents = int(round(float(credit_text) * 100)) if credit_text else 0
                if not credit_cents:
                    raise ValueError('Bitte einen Betrag größer oder kleiner als 0 eingeben.')
                app_management_views._api(
                    request,
                    f'customers/{customer_id}/',
                    method='POST',
                    payload={'credit_delta_cents': credit_cents},
                )
                return _wallet_redirect(q=request.POST.get('q') or '', notice='wallet')

        query = str(request.GET.get('q') or '').strip()
        data = app_management_views._api(request, 'customers/', query={'q': query})
        for customer in data.get('customers', []):
            cents = int(customer.get('credit_cents') or 0)
            customer['credit_eur'] = f'{cents / 100:.2f}'.replace('.', ',')

        return render(request, 'booking/app_wallet_management.html', {
            'section': 'wallet',
            'section_title': 'A+ Wallet',
            'section_subtitle': 'QR-Karte scannen, Guthaben prüfen und direkt aufladen oder abbuchen',
            'data': data,
            'query': query,
            'scan_resolved': request.GET.get('scan') == '1',
            'notice': request.GET.get('notice') or '',
        })
    except PermissionError as exc:
        return render(request, 'booking/app_wallet_management.html', {
            'section': 'wallet',
            'section_title': 'A+ Wallet',
            'section_subtitle': 'QR-Karte scannen, Guthaben prüfen und direkt aufladen oder abbuchen',
            'data': {},
            'query': '',
            'error': str(exc),
            'needs_reauth': True,
        }, status=403)
    except (RuntimeError, ValueError, TypeError) as exc:
        return render(request, 'booking/app_wallet_management.html', {
            'section': 'wallet',
            'section_title': 'A+ Wallet',
            'section_subtitle': 'QR-Karte scannen, Guthaben prüfen und direkt aufladen oder abbuchen',
            'data': {},
            'query': str(request.GET.get('q') or '').strip(),
            'error': str(exc),
        }, status=502)
