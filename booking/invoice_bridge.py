"""Booking-domain UI for the SAME A+ Esthetic invoice database.

No separate invoice tables; a private service-token bridge talks to the app
server. The credential never appears in HTML or client-side JavaScript.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .internal_api import _sync_token

BRIDGE_ROOT = "https://esthetic.smarbiz.sbs/api/mobile/internal/book-billing/"


def _request_bridge(request, operation, method="GET", payload=None, binary=False):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionError("Keine Berechtigung für Rechnungen.")
    profile = getattr(request.user, "aesthetic_access", None)
    if profile and profile.view_only:
        raise PermissionError("Dieses Arztkonto hat keinen Rechnungszugriff.")
    token = _sync_token()
    if not token:
        raise RuntimeError("Rechnungsanbindung nicht konfiguriert. Bitte Serververbindung prüfen.")
    if operation not in {"overview", "settings", "invoices", "goae", "quote", "draft", "patient-search", "pdf-preview", "quick-quote", "quick-draft"} and not (
        operation.startswith("services/") or operation.startswith("finalize/")
        or operation.startswith("pdf/")
    ):
        raise ValueError("Ungültige Rechnungsfunktion.")
    headers = {
        "X-Aesthetic-Patient-Sync": token,
        "Accept": "application/pdf" if binary else "application/json",
        "User-Agent": "A+Esthetic-Booking-Internal-Billing/1.0",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = BRIDGE_ROOT + operation.strip("/") + "/"
    remote = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(remote, timeout=18) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Rechnungsserver derzeit nicht erreichbar. Bitte erneut versuchen.") from exc
    if binary and status < 400:
        if not raw.startswith(b"%PDF"):
            raise RuntimeError("Rechnungs-PDF konnte nicht geladen werden.")
        return raw
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ungültige Antwort der Rechnungsdatenbank.") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Ungültige Antwort der Rechnungsdatenbank.")
    if status == 401 or status == 403:
        raise PermissionError("Die interne Rechnungsanbindung muss serverseitig freigeschaltet werden.")
    if status == 429 or status >= 500:
        raise RuntimeError("Rechnungsserver vorübergehend nicht verfügbar. Bitte erneut versuchen.")
    if status >= 400 or not result.get("ok"):
        # Never expose remote exception traces or internal credential details.
        reason = str(result.get("message") or result.get("error") or "Unbekannter Fehler")[:180]
        raise ValueError("Rechnungsaktion nicht möglich: " + reason)
    return result


@never_cache
@staff_member_required(login_url="/verwaltung/login/")
@require_GET
def invoice_pdf(request, invoice_id):
    try:
        data = _request_bridge(request, f"pdf/{invoice_id}", binary=True)
    except PermissionError:
        return HttpResponseForbidden("Keine Berechtigung für dieses Dokument.")
    except (RuntimeError, ValueError) as exc:
        return HttpResponse(str(exc), status=503, content_type="text/plain; charset=utf-8")
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Rechnung-{invoice_id}.pdf"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_POST
def goae_preview_pdf(request):
    if len(request.body) > 150000:
        return JsonResponse({'ok': False, 'message': 'Zu viele Rechnungsdaten.'}, status=413)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError('Ungültige Vorschauangaben.')
        data = _request_bridge(request, 'pdf-preview', method='POST', payload=payload, binary=True)
    except PermissionError:
        return JsonResponse({'ok': False, 'message': 'Keine Berechtigung für dieses Dokument.'}, status=403)
    except (RuntimeError, ValueError, TypeError) as exc:
        return JsonResponse({'ok': False, 'message': str(exc)[:200]}, status=400)
    response = HttpResponse(data, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="GOAE-Rechnungsentwurf.pdf"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
