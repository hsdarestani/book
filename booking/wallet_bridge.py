"""Authenticated Booking server wallet proxy; shares the app's actual wallet DB."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .internal_api import _sync_token

WALLET_BRIDGE_ROOT = "https://esthetic.smarbiz.sbs/api/mobile/internal/book-wallet/"


def wallet_request(request, operation, *, method="GET", payload=None, query=None):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionError("Keine Verwaltungsberechtigung.")
    access = getattr(request.user, "aesthetic_access", None)
    if access is not None and access.view_only:
        raise PermissionError("Dieses Arztkonto hat keinen Zugriff auf A+ Punkte.")
    token = _sync_token()
    if not token:
        raise RuntimeError("Punkteverwaltung ist noch nicht mit dem App Server verbunden.")
    # Strict dispatch; user input never becomes an arbitrary remote endpoint.
    permitted = (
        operation in {"customers", "lookup"}
        or (operation.startswith("history/") and operation[8:].isdigit())
        or (operation.startswith("adjust/") and operation[7:].isdigit())
    )
    if not permitted:
        raise ValueError("Ungültige Punktefunktion.")
    url = WALLET_BRIDGE_ROOT + operation.strip("/") + "/"
    if query:
        url += "?" + urlencode({k: v for k, v in query.items() if k in {"q"} and v})
    headers = {
        "Accept": "application/json",
        "X-Aesthetic-Patient-Sync": token,
        "User-Agent": "A+Esthetic-Booking-Internal-Wallet/1.0",
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        with urlopen(Request(url, headers=headers, data=body, method=method), timeout=16) as res:
            raw, status = res.read(), res.status
    except HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("A+ Punkte sind vorübergehend nicht erreichbar.") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ungültige Antwort vom Punkte Server.") from exc
    if status in (401, 403):
        raise PermissionError("Die Punkteanbindung ist noch nicht freigeschaltet.")
    if status >= 400 or not result.get("ok"):
        raise ValueError("Punkteaktion fehlgeschlagen: " + str(result.get("error") or "Serverfehler")[:120])
    return result
