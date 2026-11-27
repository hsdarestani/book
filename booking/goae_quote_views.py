"""Server-side GOÄ quote preview in the existing Book administrator shell.

The remote A+ invoice database owns the tariff and calculation, not Book.
"""
import json
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .app_management_views import _billing_api, _local_view_only
from .invoice_bridge import _request_bridge


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def goae_quote(request):
    if _local_view_only(request):
        return JsonResponse({'ok': False, 'message': 'Dieses Konto hat keinen Rechnungszugriff.'}, status=403)
    if len(request.body) > 150000:
        return JsonResponse({'ok': False, 'message': 'Zu viele Positionsdaten. Bitte Positionen und Beschreibungen prüfen.'}, status=413)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('Ungültige Angaben.')
        result = _billing_api(request, 'billing/quote/', method='POST', payload=data)
    except PermissionError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:240]}, status=403)
    except RuntimeError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:240]}, status=502)
    except (ValueError, TypeError) as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:240]}, status=400)
    response = JsonResponse(result)
    response['Cache-Control'] = 'private, no-store'
    return response


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def goae_patient_search(request):
    if _local_view_only(request):
        return JsonResponse({'ok': False}, status=403)
    try:
        data = json.loads(request.body) if len(request.body) <= 1024 else None
    except (UnicodeError, ValueError):
        data = None
    query = data.get('query') if isinstance(data, dict) else None
    offset = data.get('offset', 0) if isinstance(data, dict) else None
    if (not isinstance(query, str) or not query.isprintable() or not 2 <= len(query.strip()) <= 80
            or type(offset) is not int or not 0 <= offset <= 100000):
        return JsonResponse({'ok': False}, status=400)
    try:
        result = _request_bridge(request, 'patient-search', method='POST', payload={'query': query.strip(), 'offset': offset})
    except PermissionError:
        return JsonResponse({'ok': False}, status=403)
    except (ValueError, RuntimeError):
        return JsonResponse({'ok': False}, status=502)
    return JsonResponse(result)



@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def goae_quick(request):
    if _local_view_only(request):
        return JsonResponse({'ok': False}, status=403)
    try:
        data = json.loads(request.body) if len(request.body) <= 4096 else None
        if not isinstance(data, dict) or data.get('operation') not in {'quote', 'draft'}:
            raise ValueError('Ungültige Entwurfsangaben.')
        operation = data.pop('operation')
        result = _request_bridge(request, f'quick-{operation}', method='POST', payload=data)
    except PermissionError:
        return JsonResponse({'ok': False}, status=403)
    except (ValueError, RuntimeError, TypeError, UnicodeError) as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:200]}, status=400)
    return JsonResponse(result)
