"""Server-side GOÄ quote preview in the existing Book administrator shell.

The remote A+ invoice database owns the tariff and calculation, not Book.
"""
import json
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .app_management_views import _billing_api, _local_view_only


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def goae_quote(request):
    if _local_view_only(request):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    if len(request.body) > 150000:
        return JsonResponse({'ok': False, 'error': 'too_large'}, status=413)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('Ungültige Angaben.')
        result = _billing_api(request, 'billing/quote/', method='POST', payload=data)
    except (ValueError, TypeError, RuntimeError, PermissionError) as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:200]}, status=400)
    response = JsonResponse(result)
    response['Cache-Control'] = 'private, no-store'
    return response
