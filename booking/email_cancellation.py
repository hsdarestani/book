"""Single-appointment, signed email cancellation; never relies on a Safari session.

GET only previews a safe confirmation page. POST is CSRF-protected and never
exposes customer medical files or other bookings to a bearer-link holder.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Appointment
from .notifications import _post_internal, notify_customer_cancelled

logger = logging.getLogger(__name__)
EMAIL_CANCEL_SALT = 'aesthetic-book-email-cancel-v1'
EMAIL_CANCEL_MAX_AGE = 120 * 24 * 60 * 60
DEFAULT_RELEASE_URL = 'https://app.a-esthetic.de/api/mobile/internal/book-package-release/'


def cancellation_token(appointment):
    """Bind email access to one original appointment, owner and slot."""
    return signing.dumps(
        {
            'appointment': str(appointment.public_id),
            'customer_id': appointment.customer_id,
            'email': appointment.customer.email.strip().casefold(),
            'starts_at': appointment.starts_at.isoformat(),
        },
        salt=EMAIL_CANCEL_SALT,
        compress=True,
    )


def _validate_email_token(token, appointment):
    if not token or len(token) > 1500:
        return False
    try:
        data = signing.loads(
            token, salt=EMAIL_CANCEL_SALT, max_age=EMAIL_CANCEL_MAX_AGE,
        )
    except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError):
        return False
    return (
        isinstance(data, dict)
        and data.get('appointment') == str(appointment.public_id)
        and data.get('customer_id') == appointment.customer_id
        and data.get('email') == appointment.customer.email.strip().casefold()
        and data.get('starts_at') == appointment.starts_at.isoformat()
    )


def _render(request, appointment, *, message='', status=200, done=False, can_cancel=False, token=''):
    local = timezone.localtime(appointment.starts_at)
    response = render(request, 'booking/email_cancellation.html', {
        'appointment': appointment,
        'local_start': local,
        'message': message,
        'done': done,
        'can_cancel': can_cancel,
        'token': token,
        'deadline_hours': max(1, int(getattr(settings, 'BOOKING_CHANGE_DEADLINE_HOURS', 24))),
    }, status=status)
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response


@never_cache
@require_http_methods(['GET', 'POST'])
def cancel_from_email(request, appointment_id):
    # The public UUID is only a locator. Authorization is the signed,
    # time-limited, slot-bound token. No customer session is consulted.
    item = get_object_or_404(
        Appointment.objects.select_related('customer', 'service', 'staff'),
        public_id=appointment_id,
    )
    token = (request.POST if request.method == 'POST' else request.GET).get('token', '')
    if not _validate_email_token(token, item):
        return _render(request, item,
                       message='Dieser Link ist ungültig oder abgelaufen. Bitte kontaktiere die Praxis.',
                       status=403)

    if item.status == 'cancelled':
        return _render(request, item, message='Dieser Termin ist bereits storniert.', done=True)
    if item.status not in ('new', 'confirmed'):
        return _render(request, item, message='Dieser Termin kann nicht mehr online storniert werden.')
    deadline = item.starts_at - timedelta(
        hours=max(1, int(getattr(settings, 'BOOKING_CHANGE_DEADLINE_HOURS', 24))),
    )
    if timezone.now() > deadline:
        return _render(request, item, message='Die Stornierungsfrist ist abgelaufen. Bitte kontaktiere die Praxis.')
    if request.method == 'GET':
        return _render(request, item, can_cancel=True, token=token)

    with transaction.atomic():
        item = Appointment.objects.select_for_update().select_related(
            'customer', 'service', 'staff',
        ).get(pk=item.pk)
        if not _validate_email_token(token, item):
            return _render(request, item,
                           message='Die Termindaten wurden geändert. Bitte verwende die neue Bestätigung.',
                           status=403)
        if item.status == 'cancelled':
            return _render(request, item, message='Dieser Termin ist bereits storniert.', done=True)
        if item.status not in ('new', 'confirmed') or timezone.now() > (
            item.starts_at - timedelta(hours=max(1, int(getattr(settings, 'BOOKING_CHANGE_DEADLINE_HOURS', 24))))
        ):
            return _render(request, item, message='Dieser Termin kann nicht mehr online storniert werden.', status=409)

        # Use the same trusted Book/App relay as other notifications, but with
        # a strictly scoped operation. A package reservation, if any, must be
        # released before we confirm the cancellation to the patient.
        release = _post_internal(
            getattr(settings, 'AESTHETIC_PACKAGE_RELEASE_INTERNAL_URL', DEFAULT_RELEASE_URL),
            {'booking_public_id': str(item.public_id)},
        )
        if not release.get('ok'):
            logger.warning('Email cancellation package release could not be confirmed: booking=%s', item.pk)
            return _render(request, item,
                           message='Der Termin konnte gerade nicht sicher storniert werden. Bitte versuche es später erneut oder kontaktiere die Praxis.',
                           status=503)
        item.status = 'cancelled'
        item.save(update_fields=['status', 'updated_at'])

    try:
        notify_customer_cancelled(item)
    except Exception:
        # The cancellation was committed. A push/email outage must not turn
        # that success into a retry-able 500.
        logger.exception('Email cancellation notifications failed after commit: appointment=%s', item.pk)
    return _render(request, item, message='Dein Termin wurde storniert.', done=True)
