"""Admin safety alerts when a SimplyBook time block overlaps an existing booking.

Record only real changes from the source. The same unchanged block does not
cause repeated notifications on subsequent 10-minute SimplyBook syncs.
The reminder timer also retries failed individual channels.
"""
import logging
from html import escape

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from booking.emails import _admin_bcc_recipients, _send_html_mail, _public_base_url
from booking.models import Appointment, BlockedBookingConflictAlert
from booking.notifications import _push

logger = logging.getLogger(__name__)


def enqueue_block_conflicts(block, *, source_note_id=""):
    """Queue alerts only for already-created, still-active overlapping bookings."""
    now = timezone.now()
    if not (block.reason or "").startswith("[BLOCKNOTE]") or block.ends_at <= now:
        return 0
    overlapping = (
        Appointment.objects.filter(
            staff_id=block.staff_id,
            status__in=["new", "confirmed"],
            starts_at__lt=block.ends_at,
            ends_at__gt=max(block.starts_at, now),
            created_at__lt=now,
        )
        .select_related("customer", "service", "staff")
        .order_by("starts_at")
    )
    created = 0
    for appointment in overlapping:
        BlockedBookingConflictAlert.objects.create(
            appointment=appointment,
            blocked_period=block,
            source_note_id=str(source_note_id or "")[:80],
            block_starts_at=block.starts_at,
            block_ends_at=block.ends_at,
            appointment_starts_at=appointment.starts_at,
        )
        created += 1
    return created


def resolve_block_conflicts(block):
    """Mark previous events resolved when a source block changes or is removed."""
    return BlockedBookingConflictAlert.objects.filter(
        blocked_period=block, resolved_at__isnull=True,
    ).update(resolved_at=timezone.now())


def _overlap_remains(alert):
    block = alert.blocked_period
    appointment = alert.appointment
    if (
        block is None
        or not (block.reason or "").startswith("[BLOCKNOTE]")
        or block.starts_at != alert.block_starts_at
        or block.ends_at != alert.block_ends_at
        or appointment.status not in ("new", "confirmed")
        or appointment.staff_id != block.staff_id
    ):
        return False
    now = timezone.now()
    return (
        appointment.ends_at > now
        and appointment.starts_at < block.ends_at
        and appointment.ends_at > block.starts_at
    )


def _send_admin_conflict_email(alert):
    primary = str(getattr(settings, "BOOKING_NOTIFICATION_EMAIL", "") or "").strip()
    if not primary:
        raise ValueError("No admin email configured for blocking conflict alert")
    appointment = alert.appointment
    booking_time = timezone.localtime(appointment.starts_at)
    block_start = timezone.localtime(alert.block_starts_at)
    block_end = timezone.localtime(alert.block_ends_at)
    admin_url = f"{_public_base_url()}/verwaltung/#termine"
    subject = "ACHTUNG: Terminkonflikt nach SimplyBook Sperre"
    message = (
        "WICHTIG: SimplyBook hat eine Sperre für einen bereits gebuchten Termin synchronisiert.\n"
        "Bitte den Termin prüfen und die Patientin oder den Patienten bei Bedarf kontaktieren.\n"
        "Die Buchung wurde NICHT automatisch storniert.\n\n"
        f"Patient: {appointment.customer.full_name}\n"
        f"Behandlung: {appointment.service.name}\n"
        f"Behandler: {appointment.staff.display_name}\n"
        f"Bestehender Termin: {booking_time:%d.%m.%Y %H:%M}\n"
        f"Neue Sperre: {block_start:%d.%m.%Y %H:%M} bis {block_end:%d.%m.%Y %H:%M}\n"
        f"Kalender: {admin_url}\n"
    )
    html = (
        "<div style='font-family:Arial,sans-serif;max-width:600px;margin:auto;"
        "color:#15263c;line-height:1.65'>"
        "<h2 style='color:#9c2931'>Achtung: Terminkonflikt</h2>"
        "<p>Eine neue oder geänderte SimplyBook Sperre überschneidet sich "
        "mit einem bestehenden Termin. <b>Die Buchung bleibt bestehen.</b></p>"
        "<p><b>Patient:</b> " + escape(appointment.customer.full_name) + "<br>"
        "<b>Behandlung:</b> " + escape(appointment.service.name) + "<br>"
        "<b>Behandler:</b> " + escape(appointment.staff.display_name) + "<br>"
        "<b>Termin:</b> " + escape(booking_time.strftime("%d.%m.%Y %H:%M")) + "<br>"
        "<b>Sperre:</b> " + escape(block_start.strftime("%d.%m.%Y %H:%M"))
        + " bis " + escape(block_end.strftime("%d.%m.%Y %H:%M")) + "</p>"
        "<p>Bitte diesen Konflikt prüfen und den Termin bei Bedarf abstimmen.</p>"
        "<p><a href='" + escape(admin_url, quote=True)
        + "'>Zum Terminplaner</a></p></div>"
    )
    _send_html_mail(subject, message, html, [primary], bcc=_admin_bcc_recipients())


def _send_admin_conflict_push(alert):
    appointment = alert.appointment
    local = timezone.localtime(appointment.starts_at)
    start = timezone.localtime(alert.block_starts_at)
    end = timezone.localtime(alert.block_ends_at)
    return _push(
        appointment, target="admin", event="simplybook_block_conflict",
        title="Achtung: Termin trotz Sperre",
        body=(
            f"{appointment.customer.full_name} · {local:%d.%m. %H:%M} · "
            f"{appointment.staff.display_name} · Sperre {start:%H:%M} bis {end:%H:%M}. "
            "Bitte prüfen; Termin bleibt bestehen."
        ),
    )


def process_pending_block_conflict_alerts(limit=100):
    """Attempt each missing channel once; never re-send an accepted channel."""
    attempted = email_sent = push_sent = unresolved = 0
    pending = list(
        BlockedBookingConflictAlert.objects.filter(resolved_at__isnull=True)
        .filter(Q(email_sent_at__isnull=True) | Q(push_sent_at__isnull=True))
        .values_list("pk", flat=True)
        .order_by("created_at", "pk")[:limit]
    )
    for pk in pending:
        with transaction.atomic():
            alert = (
                BlockedBookingConflictAlert.objects.select_for_update(of=('self',))
                .select_related(
                    "blocked_period", "appointment__customer",
                    "appointment__service", "appointment__staff",
                )
                .filter(pk=pk, resolved_at__isnull=True)
                .first()
            )
            if alert is None:
                continue
            if not _overlap_remains(alert):
                alert.resolved_at = timezone.now()
                alert.save(update_fields=["resolved_at"])
                continue

            attempted += 1
            if alert.email_sent_at is None:
                try:
                    _send_admin_conflict_email(alert)
                    alert.email_sent_at = timezone.now()
                    alert.save(update_fields=["email_sent_at"])
                    email_sent += 1
                except Exception:
                    logger.exception("Could not send admin SimplyBook block-conflict email")

            if alert.push_sent_at is None:
                try:
                    result = _send_admin_conflict_push(alert)
                    if result.get("ok"):
                        alert.push_sent_at = timezone.now()
                        alert.save(update_fields=["push_sent_at"])
                        push_sent += 1
                    else:
                        logger.warning(
                            "Could not relay admin SimplyBook block conflict push: %s",
                            result.get("error", "unknown"),
                        )
                except Exception:
                    logger.exception("Could not relay admin SimplyBook block-conflict push")
            if alert.email_sent_at is None or alert.push_sent_at is None:
                unresolved += 1

    return {
        "attempted": attempted,
        "email_sent": email_sent,
        "push_submitted": push_sent,
        "pending_retry": unresolved,
    }
