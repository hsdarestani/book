"""Source-first scheduling for active Ariane appointments with verified IDs."""
import os
from copy import copy

from django.utils import timezone

from .clinical_time import add_elapsed, clinic_localtime
from .models import Appointment, BlockedPeriod, SimplyBookClientLink
from .simplybook_outbound import (
    ARIANE, SERVICE_MAP, SOURCE_AVAILABILITY_ERRORS, UNIT_ID, SyncConflict, _same_booking,
    _verify_availability, _verify_readback, as_bool, session,
)


def source_id(item):
    raw = str(item.simplybook_booking_id or (item.idempotency_key or '').removeprefix('simplybook-'))
    if not (item.simplybook_booking_id or (item.idempotency_key or '').startswith('simplybook-')):
        return None
    return int(raw) if raw.isdecimal() and int(raw) > 0 else None


def source_managed(item):
    return bool(item.simplybook_booking_id or item.simplybook_sync_state
                or (item.idempotency_key or '').startswith('simplybook-'))


def source_editable(item):
    return (os.getenv('SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED', '').lower() == 'true'
            and item.staff.display_name == ARIANE and item.starts_at > timezone.now()
            and item.status == 'confirmed' and item.simplybook_sync_state in {'', 'linked'}
            and source_id(item) is not None)


def _details(call, remote_id):
    row = call('getBookingDetails', [remote_id])
    if not isinstance(row, dict) or str(row.get('id')) != str(remote_id):
        raise SyncConflict('source_booking_readback_mismatch')
    return row


def _identity(item, remote=None):
    if item.simplybook_booking_id:
        mapping = SERVICE_MAP.get(item.service.slug)
        client = item.simplybook_client_id
        event = item.simplybook_event_id
        if not mapping or str(mapping[0]) != event:
            raise SyncConflict('source_service_mismatch')
    else:
        slug = item.service.slug
        event = slug.removeprefix('simplybook-event-') if slug.startswith('simplybook-event-') else ''
        links = SimplyBookClientLink.objects.filter(customer_id=item.customer_id)
        if remote is not None:
            client = str(remote.get('client_id') or '')
            if not links.filter(external_client_id=client).exists():
                raise SyncConflict('source_client_not_verified')
        else:
            clients = list(links.values_list('external_client_id', flat=True)[:2])
            if len(clients) != 1:
                raise SyncConflict('source_client_not_unique')
            client = clients[0]
    if not (str(event).isdecimal() and str(client).isdecimal()):
        raise SyncConflict('source_identity_unverified')
    return int(event), int(client)


def _additional_values(call, event, remote):
    """Copy only source field values whose identity and shape we can verify."""
    values = remote.get('additional_fields')
    if values in (None, {}, [], ''):
        return {}
    if isinstance(values, list):
        mapped = {}
        for field in values:
            if not isinstance(field, dict):
                raise SyncConflict('source_fields_require_review')
            name, value = field.get('field_name'), field.get('value')
            if not isinstance(name, str) or not name or name in mapped or not isinstance(value, str):
                raise SyncConflict('source_fields_require_review')
            mapped[name] = value
        values = mapped
    if not isinstance(values, dict) or not all(isinstance(value, str) for value in values.values()):
        raise SyncConflict('source_fields_require_review')
    definitions = call('getAdditionalFields', [event])
    if not isinstance(definitions, list) or any(not isinstance(field, dict) for field in definitions):
        raise SyncConflict('source_fields_require_review')
    fields = {str(field.get('name')): field for field in definitions}
    if set(values) - fields.keys():
        raise SyncConflict('source_fields_require_review')
    for name, field in fields.items():
        required = any(as_bool(field.get(key)) for key in ('required', 'is_required', 'mandatory', 'is_mandatory'))
        value = values.get(name, '')
        if required and not value:
            raise SyncConflict('source_fields_require_review')
        choices = [choice.strip() for choice in str(field.get('values') or '').split(',') if choice.strip()]
        if choices and value and value not in choices:
            raise SyncConflict('source_fields_require_review')
    return values


def _verified_cancellation(call, item, remote_id, event, client):
    detail = _details(call, remote_id)
    if (str(detail.get('event_id')) != str(event) or str(detail.get('client_id')) != str(client)
            or str(detail.get('unit_id')) != str(UNIT_ID)):
        return False
    if as_bool(detail.get('is_cancelled', detail.get('is_canceled'))) or str(detail.get('status') or '').lower() in {
        'cancelled', 'canceled',
    }:
        return True
    if as_bool(detail.get('is_confirmed', detail.get('is_confirm'))):
        return False
    day = clinic_localtime(item.starts_at).date().isoformat()
    params = {'date_from': day, 'date_to': day, 'booking_type': 'cancelled'}
    cancelled = call('getBookings', [params])
    if not isinstance(cancelled, list):
        return False
    return sum(
        isinstance(row, dict) and str(row.get('id')) == str(remote_id)
        and str(row.get('event_id')) == str(event) and str(row.get('client_id')) == str(client)
        and str(row.get('unit_id')) == str(UNIT_ID)
        for row in cancelled
    ) == 1


def change_locked(item, *, starts_at=None, cancel=False, call=None):
    """The caller holds the provider and appointment locks.

    Return False after an uncertain write so the caller can commit its review
    state and return a conflict, keeping automatic and user retries blocked.
    """
    if not source_editable(item):
        raise SyncConflict('source_booking_not_editable')
    remote_id = source_id(item)
    call = call or session()
    remote = _details(call, remote_id)
    event, client = _identity(item, remote)
    expected = copy(item)
    expected.ends_at = item.simplybook_remote_ends_at or item.ends_at
    if not _same_booking(remote, expected, event, client):
        raise SyncConflict('source_booking_changed')
    if (remote.get('invoice_id') not in (None, 0, '0', '')
            or remote.get('invoice_payment_received') not in (None, 0, '0', '')
            or as_bool(remote.get('deposit_is_enabled'))
            or remote.get('price') not in (None, {}, [], '')
            or remote.get('promo') not in (None, {}, [], '')
            or remote.get('batch_id') not in (None, 0, '0', '')):
        raise SyncConflict('source_payment_requires_review')

    target = copy(item)
    remote_end = None
    if cancel:
        method, params = 'cancelBooking', [remote_id]
    else:
        if starts_at is None or starts_at <= timezone.now():
            raise SyncConflict('source_slot_unavailable')
        if starts_at == item.starts_at:
            return True
        if remote.get('location') not in (None, {}, [], ''):
            raise SyncConflict('source_location_requires_review')
        target.starts_at = starts_at
        target.ends_at = add_elapsed(starts_at, item.reserved_duration)
        remote_end = add_elapsed(starts_at, expected.reserved_duration)
        if (Appointment.objects.filter(
                staff=item.staff, status__in=['new', 'confirmed'], starts_at__lt=target.ends_at,
                ends_at__gt=target.starts_at).exclude(pk=item.pk).exists()
                or BlockedPeriod.objects.filter(
                    staff=item.staff, starts_at__lt=target.ends_at, ends_at__gt=target.starts_at
                ).exclude(reason__startswith='[NOTE]').exists()):
            raise SyncConflict('local_interval_unavailable')
        if _verify_availability(call, target, event, client, exclude_source_id=remote_id, remote_end=remote_end):
            raise SyncConflict('source_booking_conflict')
        additional = _additional_values(call, event, remote)
        start, end = clinic_localtime(target.starts_at), clinic_localtime(remote_end)
        method = 'editBook'
        params = [remote_id, event, UNIT_ID, client, start.strftime('%Y-%m-%d'),
                  start.strftime('%H:%M:%S'), end.strftime('%Y-%m-%d'), end.strftime('%H:%M:%S'),
                  int(remote.get('client_time_offset') or 0), additional]

    try:
        call(method, params)
        if cancel:
            if not _verified_cancellation(call, item, remote_id, event, client):
                raise SyncConflict('source_cancellation_unverified')
        else:
            _verify_readback(call, remote_id, target, event, client, remote_end=remote_end)
            if additional and _additional_values(call, event, _details(call, remote_id)) != additional:
                raise SyncConflict('source_fields_require_review')
    except SOURCE_AVAILABILITY_ERRORS:
        item.simplybook_sync_state = 'review'
        item.save(update_fields=['simplybook_sync_state', 'updated_at'])
        return False

    if cancel:
        item.status = 'cancelled'
        item.save(update_fields=['status', 'updated_at'])
    else:
        item.starts_at, item.ends_at = target.starts_at, target.ends_at
        item.simplybook_remote_ends_at = remote_end
        item.reminder_24h_sent_at = None
        item.reminder_1h_sent_at = None
        item.reminder_1h_admin_email_sent_at = None
        item.reminder_1h_admin_push_sent_at = None
        item.save(update_fields=['starts_at', 'ends_at', 'simplybook_remote_ends_at', 'updated_at', 'reminder_24h_sent_at',
                                 'reminder_1h_sent_at', 'reminder_1h_admin_email_sent_at',
                                 'reminder_1h_admin_push_sent_at'])
    return True
