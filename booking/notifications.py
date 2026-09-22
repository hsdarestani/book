import json
import logging
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone


logger = logging.getLogger(__name__)
DEFAULT_RELAY_URL = "https://esthetic.smarbiz.sbs/api/mobile/internal/booking-notifications/"


def _sync_token():
    direct = str(getattr(settings, "PATIENT_SYNC_TOKEN", "") or "").strip()
    if direct:
        return direct
    token_file = Path(getattr(settings, "PATIENT_SYNC_TOKEN_FILE", "/etc/aesthetic-patient-sync.token"))
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _relay(payload):
    token = _sync_token()
    if not token:
        logger.warning("Booking push relay skipped: sync token is not configured")
        return {"ok": False, "error": "sync_token_missing"}

    url = str(getattr(settings, "AESTHETIC_BOOKING_NOTIFICATION_URL", DEFAULT_RELAY_URL) or DEFAULT_RELAY_URL)
    request = Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-Aesthetic-Patient-Sync": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Aesthetic-Booking-Push/1.0",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result if isinstance(result, dict) else {"ok": False, "error": "invalid_relay_response"}
    except HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            result = {}
        logger.warning("Booking push relay HTTP %s: %s", exc.code, result or exc.reason)
        return result if isinstance(result, dict) and result else {"ok": False, "error": f"relay_http_{exc.code}"}
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Booking push relay unavailable: %s", exc)
        return {"ok": False, "error": "relay_unavailable"}


def appointment_snapshot(appointment):
    return {
        "status": appointment.status,
        "starts_at": appointment.starts_at.isoformat() if appointment.starts_at else "",
        "service_id": appointment.service_id,
        "staff_id": appointment.staff_id,
        "customer_id": appointment.customer_id,
    }


def _local_start(appointment):
    return timezone.localtime(appointment.starts_at)


def _payload(appointment, *, target, event, title, body):
    return {
        "target": target,
        "event": event,
        "title": title,
        "body": body,
        "customer_email": appointment.customer.email,
        "booking_public_id": str(appointment.public_id),
        "status": appointment.status,
        "starts_at": appointment.starts_at.isoformat(),
        "source": appointment.source,
    }


def _send(appointment, *, target, event, title, body):
    return _relay(_payload(
        appointment,
        target=target,
        event=event,
        title=title,
        body=body,
    ))


def notify_booking_created(appointment):
    local = _local_start(appointment)
    customer = _send(
        appointment,
        target="customer",
        event="booking_created",
        title="Termin gebucht",
        body=f"Ihr Termin für {appointment.service.name} am {local:%d.%m.%Y} um {local:%H:%M} wurde gespeichert.",
    )
    admin = _send(
        appointment,
        target="admin",
        event="booking_created",
        title="Neue Buchung",
        body=f"{appointment.customer.full_name} · {appointment.service.name} · {local:%d.%m.%Y %H:%M} · {appointment.staff.display_name}",
    )
    return {"customer": customer, "admin": admin}


def notify_customer_cancelled(appointment):
    local = _local_start(appointment)
    customer = _send(
        appointment,
        target="customer",
        event="customer_cancelled",
        title="Termin storniert",
        body=f"Ihr Termin für {appointment.service.name} am {local:%d.%m.%Y} um {local:%H:%M} wurde storniert.",
    )
    admin = _send(
        appointment,
        target="admin",
        event="customer_cancelled",
        title="Termin storniert",
        body=f"{appointment.customer.full_name} hat den Termin {appointment.service.name} am {local:%d.%m.%Y um %H:%M} storniert.",
    )
    return {"customer": customer, "admin": admin}


def notify_customer_rescheduled(appointment):
    local = _local_start(appointment)
    customer = _send(
        appointment,
        target="customer",
        event="customer_rescheduled",
        title="Termin verschoben",
        body=f"Ihr Termin wurde auf {local:%d.%m.%Y} um {local:%H:%M} verschoben.",
    )
    admin = _send(
        appointment,
        target="admin",
        event="customer_rescheduled",
        title="Termin verschoben",
        body=f"{appointment.customer.full_name} hat den Termin auf {local:%d.%m.%Y um %H:%M} verschoben · {appointment.service.name}.",
    )
    return {"customer": customer, "admin": admin}


def notify_admin_created(appointment):
    local = _local_start(appointment)
    return _send(
        appointment,
        target="customer",
        event="admin_created",
        title="Neuer Termin",
        body=f"Für Sie wurde ein Termin für {appointment.service.name} am {local:%d.%m.%Y} um {local:%H:%M} eingetragen.",
    )


def notify_admin_changed(appointment, previous):
    current = appointment_snapshot(appointment)
    if current == previous:
        return {"ok": True, "skipped": "unchanged"}

    local = _local_start(appointment)
    status_changed = previous.get("status") != appointment.status
    event = "admin_status_changed" if status_changed else "admin_rescheduled"
    titles = {
        "new": "Termin aktualisiert",
        "confirmed": "Termin bestätigt",
        "cancelled": "Termin abgesagt",
        "completed": "Termin abgeschlossen",
        "no_show": "Terminstatus aktualisiert",
    }
    title = titles.get(appointment.status, "Termin aktualisiert")
    if not status_changed:
        title = "Termin geändert"

    status_text = appointment.get_status_display()
    return _send(
        appointment,
        target="customer",
        event=event,
        title=title,
        body=f"{appointment.service.name} · {local:%d.%m.%Y} um {local:%H:%M} · Status: {status_text}.",
    )


def notify_admin_deleted(appointment):
    local = _local_start(appointment)
    return _send(
        appointment,
        target="customer",
        event="admin_deleted",
        title="Termin abgesagt",
        body=f"Ihr Termin für {appointment.service.name} am {local:%d.%m.%Y} um {local:%H:%M} wurde abgesagt.",
    )


def notify_24h_reminder(appointment):
    local = _local_start(appointment)
    return _send(
        appointment,
        target="customer",
        event="reminder_24h",
        title="Terminerinnerung",
        body=f"Ihr Termin für {appointment.service.name} ist am {local:%d.%m.%Y} um {local:%H:%M} bei {appointment.staff.display_name}.",
    )
