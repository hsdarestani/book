"""Prevent external test automation from creating real reservations as the shared demo account."""
import logging

LOGGER = logging.getLogger(__name__)

DEMO_EMAIL = "demo@a-esthetic.de"


def is_blocked_demo_customer(email):
    return str(email or "").strip().casefold() == DEMO_EMAIL


def blocked_demo_response():
    from django.http import JsonResponse
    return JsonResponse({
        "ok": False,
        "error": "demo_booking_disabled",
        "message": "Mit dem Demokonto können keine echten Termine gebucht werden.",
    }, status=403)


def log_blocked_demo_booking(route):
    # Do not log a customer's token, e-mail, personal details or request body.
    LOGGER.warning("DEMO_BOOKING_BLOCKED route=%s", route)
