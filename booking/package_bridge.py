import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings


DEFAULT_PACKAGE_API_URL = "https://esthetic.smarbiz.sbs/api/mobile/package-booking/"


def sync_package(authorization, action, appointment):
    """Reserve/release one Customer Club package session for a book appointment.

    This is intentionally idempotent on the Customer Club side and best-effort:
    a temporary package-service outage must never corrupt or block the canonical
    appointment stored in book.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return {"ok": False, "package_used": False, "error": "authentication_required"}

    url = getattr(settings, "AESTHETIC_PACKAGE_API_URL", DEFAULT_PACKAGE_API_URL)
    payload = {
        "action": action,
        "booking_public_id": str(appointment.public_id),
        "service_slug": appointment.service.slug,
        "service_name": appointment.service.name,
    }
    request = Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Aesthetic-Booking/1.0",
        },
    )
    try:
        with urlopen(request, timeout=6) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else {"ok": False, "package_used": False}
    except HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        return {"ok": False, "package_used": False, "error": "package_service_http_error"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return {"ok": False, "package_used": False, "error": "package_service_unavailable"}
