"""Controlled, source-first creation of a single existing local Ariane booking.

No automatic retries after an uncertain remote write. Only explicit, reviewed
service mappings are accepted. The importer preserves the local UUID and key.
"""
from copy import copy
import os
import logging
import re
import shlex
from pathlib import Path
from datetime import UTC
from django.db import models, transaction
from django.utils import timezone
from .clinical_time import CLINIC_TZ, parse_appointment_start, parse_clinic_wall_time
from .models import Appointment, SimplyBookClientLink
from .customer_identity import normalize_name, normalize_email, normalize_phone
from .management.commands.simplybook_import import rpc, LOGIN_URL, ADMIN_URL, RpcError, as_bool

logger = logging.getLogger(__name__)
ARIANE = 'Frau Ariane Regaei'
# Actual active, bookable Ariane catalog and source catalog verified live
# 2026-11-26. Explicit IDs; never fuzzy-match medical services.
SERVICE_MAP = {
    'aesthetische-erstberatung': (8, 'Erstberatung'),
    'botox-neupatient': (2, 'Botox-Behandlung (Neupatient)'),
    'botox-bestandspatient': (10, 'Botox-Behandlung (Bestandspatient)'),
    'hyaluron': (3, 'Hyaluronsäure-Behandlungen'),
    'infusionstherapie': (4, 'Infusionstherapien'),
    'injektionslipolyse': (11, 'Lipolyse-Injektion'),
    'kontrolltermin': (9, 'Kontrolltermin'),
    'laser-haarentfernung': (5, 'Dauerhafte Haarentfernung  (Alexandrit - Nd:YAG)'),
    'rf-microneedling': (6, 'RF-Microneedling'),
}
UNIT_ID = 2
REFERRAL_ANSWERS = {'Google', 'Werbeanzeige in Facebook / Instagram', 'Freunde und Bekannten', 'Sonstiges'}

class SyncConflict(ValueError):
    pass


SOURCE_AVAILABILITY_ERRORS = (RpcError, OSError, ValueError, TypeError)

def _source_credentials():
    names = ('SIMPLYBOOK_COMPANY_LOGIN', 'SIMPLYBOOK_USER_LOGIN',
             'SIMPLYBOOK_API_USER_KEY', 'SIMPLYBOOK_USER_PASSWORD')
    values = {key: os.getenv(key, '') for key in names}
    directory = os.getenv('CREDENTIALS_DIRECTORY')
    if directory and not (values[names[0]] and values[names[1]] and (values[names[2]] or values[names[3]])):
        try:
            for line in (Path(directory) / 'simplybook').read_text().splitlines():
                parts = shlex.split(line)
                if len(parts) == 2 and parts[0] == 'export':
                    name, _, value = parts[1].partition('=')
                    if name in values and not values[name]:
                        values[name] = value
        except (OSError, ValueError):
            raise SyncConflict('missing_credentials') from None
    company, user, key, password = (values[name].strip() for name in names)
    return company, user, key or password


def session():
    company, user, credential = _source_credentials()
    if not all((company,user,credential)):
        raise SyncConflict('missing_credentials')
    token = rpc(LOGIN_URL,'getUserToken',[company,user,credential],timeout=20)
    if not token:
        raise SyncConflict('empty_token')
    headers = {'X-Company-Login':company,'X-User-Token':token}
    def call(method, params):
        try:
            return rpc(ADMIN_URL,method,params,headers=headers,timeout=25)
        except Exception as exc:
            # Source errors can contain patient identifiers; log only the method,
            # numeric error code and a finite vocabulary of diagnostic categories.
            message = str(exc).lower()
            code = re.search(r'(?:failed:|http)\s*(-?\d+)', message)
            categories = [k for k in ('additional','required','timeframe','duration','not available','invalid','permission','parameter','field','payment','confirmation','rate limit','too many') if k in message]
            logger.warning('SimplyBook outbound method=%s code=%s categories=%s', method, code.group(1) if code else 'unknown', ','.join(categories) or 'other')
            raise
    return call

def _dt(value):
    parsed = parse_appointment_start(value)
    return parsed.astimezone(UTC) if parsed is not None else None

def _contact_matches(row, customer):
    return (normalize_name(row.get('name')) == normalize_name(customer.full_name)
            and bool(normalize_email(customer.email))
            and normalize_email(row.get('email')) == normalize_email(customer.email)
            and bool(normalize_phone(customer.phone))
            and normalize_phone(row.get('phone')) == normalize_phone(customer.phone))

def _verify_catalog(call, item):
    if item.staff.display_name != ARIANE or item.status not in {'new','confirmed'} or item.starts_at <= timezone.now():
        raise SyncConflict('unsupported_appointment')
    if (item.idempotency_key or '').startswith('simplybook-'):
        raise SyncConflict('already_source_managed')
    mapping = SERVICE_MAP.get(item.service.slug)
    if not mapping:
        raise SyncConflict('unmapped_service')
    tz = call('getCompanyTimezoneOffset',[])
    if not isinstance(tz,dict) or tz.get('timezone') != 'Europe/Berlin':
        raise SyncConflict('unexpected_timezone')
    units = call('getUnitList',[False,True])
    active = [r for r in units if as_bool(r.get('is_active'))]
    if len(active)!=1 or str(active[0].get('id')) != str(UNIT_ID):
        raise SyncConflict('unexpected_provider_catalog')
    events = call('getEventList',[False,True,None,''])
    matches = [r for r in events if str(r.get('id'))==str(mapping[0]) and as_bool(r.get('is_active'))
               and normalize_name(r.get('name')) == normalize_name(mapping[1])]
    if len(matches)!=1:
        raise SyncConflict('source_service_mismatch')
    return mapping[0]

def _get_client(call, customer, *, apply):
    links = list(SimplyBookClientLink.objects.filter(customer=customer))
    candidates = call('getClientList',[customer.email,None])
    same_email = [r for r in candidates if normalize_email(r.get('email')) == normalize_email(customer.email)]
    exact = [r for r in same_email if _contact_matches(r,customer)]
    if len(exact)>1 or (same_email and len(exact)!=1) or len(links)>1:
        raise SyncConflict('ambiguous_client_identity')
    if exact:
        cid = int(exact[0]['id'])
    elif links:
        raise SyncConflict('linked_client_not_verified')
    elif not apply:
        return None
    else:
        cid = int(call('addClient',[{'name':customer.full_name,'email':customer.email,'phone':customer.phone,'is_email_unsubscribed':True,'is_sms_unsubscribed':True},False]))
    remote = call('getClientInfo',[cid])
    if not isinstance(remote,dict) or not _contact_matches(remote,customer):
        raise SyncConflict('source_client_readback_failed')
    if links and links[0].external_client_id != str(cid):
        raise SyncConflict('source_client_link_mismatch')
    if apply:
        link, _ = SimplyBookClientLink.objects.get_or_create(external_client_id=str(cid),defaults={
            'customer':customer,'source_name':remote['name'][:160],'source_email':remote['email'][:254],
            'source_phone':remote['phone'][:40]})
        if link.customer_id != customer.pk:
            raise SyncConflict('source_client_link_owned_by_other')
    return cid

def _additional_answers(call, item, event):
    """Read source field IDs and choices; transmit only actual local answers.

    Never invent a referral channel or a medical treatment preference. A source
    field that has no local answer stays empty if optional; explicit mandatory
    fields require a local answer before any mutation.
    """
    if not as_bool(call('isPluginActivated', ['event_field'])):
        return {}
    fields = call('getAdditionalFields', [event])
    if not isinstance(fields, list):
        raise SyncConflict('unexpected_additional_fields_shape')
    result = {}
    for field in fields:
        if not isinstance(field, dict) or not field.get('name'):
            raise SyncConflict('unexpected_additional_field')
        title = normalize_name(field.get('title'))
        values = [v.strip() for v in str(field.get('values') or '').split(',') if v.strip()]
        required = any(as_bool(field.get(key)) for key in ('required','is_required','mandatory','is_mandatory'))
        answer = ''
        if title == 'warst du schon einmal bei uns?':
            # A legacy false also represents a missing answer.
            if item.returning_customer:
                answer = 'Ja'
            elif item.returning_customer_answered:
                answer = 'Nein'
        elif title == 'wie bist du auf uns aufmerksam geworden?':
            referral = normalize_name(item.referral_source)
            aliases = {
                'google': 'Google',
                'facebook': 'Werbeanzeige in Facebook / Instagram',
                'instagram': 'Werbeanzeige in Facebook / Instagram',
                'werbeanzeige in facebook / instagram': 'Werbeanzeige in Facebook / Instagram',
                'empfehlung': 'Freunde und Bekannten',
                'freunde und bekannten': 'Freunde und Bekannten',
                'sonstiges': 'Sonstiges',
                'other': 'Sonstiges',
            }
            answer = aliases.get(referral, '')
        # Unknown or unavailable answers are intentionally not fabricated.
        if answer and values and answer not in values:
            raise SyncConflict('source_additional_choice_changed')
        if required and not answer:
            raise SyncConflict('source_additional_answer_required')
        result[str(field['name'])] = answer
    return result


def _same_booking(row, item, event, client):
    return (str(row.get('event_id'))==str(event) and str(row.get('unit_id'))==str(UNIT_ID)
            and str(row.get('client_id'))==str(client)
            and _dt(row.get('start_date_time') or row.get('start_date'))==item.starts_at
            and _dt(row.get('end_date_time') or row.get('end_date'))==item.ends_at
            and as_bool(row.get('is_confirmed',row.get('is_confirm'))))

def integrated(service, staff):
    return staff.display_name == ARIANE and service.slug in SERVICE_MAP


def patient_booking_answers(customer, *, now=None):
    """Use the resolved patient record and evidence of a completed visit."""
    now = now or timezone.now()
    history = Appointment.objects.filter(customer=customer)
    returning = history.filter(status='completed', ends_at__lte=now).exists()
    # Prefer a verified non-default answer over the owner-assigned Google default.
    referral = (history.filter(returning_customer_answered=True, referral_source__in=REFERRAL_ANSWERS)
                .exclude(referral_source='Google').order_by('-created_at')
                .values_list('referral_source', flat=True).first())
    return returning, referral or 'Google'


def public_sync_enabled():
    return os.getenv('SIMPLYBOOK_OUTBOUND_ENABLED') == '1'


def public_availability_enabled():
    return public_sync_enabled() or os.getenv('SIMPLYBOOK_AVAILABILITY_ENABLED') == '1'


def source_slots(call, event, day, end_day, exclude_source_id=None):
    matrix = call('getStartTimeMatrix', [day, end_day, event, UNIT_ID, 1])
    params = [day, end_day, event, UNIT_ID, 1]
    if exclude_source_id is not None:
        params.append(exclude_source_id)
    reserved = call('getReservedTimeIntervals', params)
    if not isinstance(matrix, dict) or not isinstance(reserved, dict):
        raise SyncConflict('unexpected_availability_shape')
    slots = {}
    blocks = []
    for date, values in matrix.items():
        if not isinstance(values, list):
            raise SyncConflict('unexpected_availability_shape')
        starts = [parse_clinic_wall_time(date, value) for value in values]
        if any(start is None for start in starts):
            raise SyncConflict('unexpected_source_slot')
        slots[date] = starts
    for date, providers in reserved.items():
        if not isinstance(providers, list):
            raise SyncConflict('unexpected_reserved_shape')
        for provider in providers:
            if not isinstance(provider, dict) or not isinstance(provider.get('reserved_time'), list):
                raise SyncConflict('unexpected_reserved_shape')
            for interval in provider['reserved_time']:
                if not isinstance(interval, dict):
                    raise SyncConflict('unexpected_reserved_shape')
                start = _dt(date + ' ' + str(interval.get('from', '')))
                finish = _dt(date + ' ' + str(interval.get('to', '')))
                if start is None or finish is None or finish <= start:
                    raise SyncConflict('unexpected_reserved_shape')
                blocks.append((start, finish))
    return slots, blocks


def _source_bookings(call, start, end):
    day = start.astimezone(CLINIC_TZ).date().isoformat()
    end_day = end.astimezone(CLINIC_TZ).date().isoformat()
    rows = call('getBookings', [{'date_from': day, 'date_to': end_day, 'booking_type': 'non_cancelled'}])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SyncConflict('unexpected_bookings_shape')
    return rows


def _verify_availability(call, item, event, client, *, exclude_source_id=None, remote_end=None):
    day = item.starts_at.astimezone(CLINIC_TZ).date().isoformat()
    end_day = item.ends_at.astimezone(CLINIC_TZ).date().isoformat()
    bookings = _source_bookings(call, item.starts_at, item.ends_at)
    expected = copy(item)
    expected.ends_at = remote_end or item.ends_at
    exact = [row for row in bookings if client and _same_booking(row, expected, event, client)]
    if len(exact) > 1:
        raise SyncConflict('duplicate_source_bookings')
    if exact:
        return int(exact[0]['id'])
    for row in bookings:
        if str(row.get('unit_id')) != str(UNIT_ID) or str(row.get('id')) == str(exclude_source_id):
            continue
        start = _dt(row.get('start_date_time') or row.get('start_date'))
        end = _dt(row.get('end_date_time') or row.get('end_date'))
        if start is None or end is None or start < item.ends_at and end > item.starts_at:
            raise SyncConflict('source_booking_conflict')
    slots, blocks = source_slots(call, event, day, end_day, exclude_source_id)
    if item.starts_at not in slots.get(day, ()):
        raise SyncConflict('source_slot_unavailable')
    if any(start < item.ends_at and end > item.starts_at for start, end in blocks):
        raise SyncConflict('source_reserved_interval_conflict')
    return None

def source_end_for_booking(call, item, event):
    if item.calendar_buffer_minutes == 0:
        return item.ends_at
    start = item.starts_at.astimezone(CLINIC_TZ).strftime('%Y-%m-%d %H:%M:%S')
    end = _dt(call('calculateEndTime', [start, event, UNIT_ID, []]))
    if end is None or not item.calendar_treatment_end <= end <= item.ends_at:
        raise SyncConflict('source_duration_mismatch')
    return end


def sync_existing(pk, *, apply=False, call=None):
    item=Appointment.objects.select_related('customer','service','staff').get(pk=pk)
    if item.simplybook_booking_id:
        return {'result':'already_linked'}
    if item.simplybook_sync_state in {'sending','review'}:
        raise SyncConflict('previous_write_requires_reconciliation')
    call=call or session()
    event=_verify_catalog(call,item)
    additional=_additional_answers(call,item,event)
    client=_get_client(call,item.customer,apply=False)
    remote_end = source_end_for_booking(call, item, event)
    previous=_verify_availability(call,item,event,client,remote_end=remote_end)
    if not apply:
        return {'result':'preflight_ok','existing_source_booking':bool(previous),'source_client_exists':bool(client)}
    # Serialize the claim before any booking mutation. A crash or timeout
    # must not permit an automatic second book() request.
    with transaction.atomic():
        locked=Appointment.objects.select_for_update().get(pk=pk)
        if (locked.simplybook_booking_id or locked.simplybook_sync_state not in {'','queued'} or
            locked.starts_at!=item.starts_at or locked.ends_at!=item.ends_at or
            locked.customer_id!=item.customer_id or locked.staff_id!=item.staff_id or
            locked.service_id!=item.service_id or locked.status!=item.status):
            raise SyncConflict('local_booking_changed')
        locked.simplybook_sync_state='sending'
        locked.simplybook_event_id=str(event)
        locked.simplybook_remote_ends_at=remote_end
        locked.save(update_fields=['simplybook_sync_state','simplybook_event_id','simplybook_remote_ends_at'])
    try:
        client=_get_client(call,item.customer,apply=True)
        Appointment.objects.filter(pk=pk,simplybook_sync_state='sending').update(simplybook_client_id=str(client))
        previous=_verify_availability(call,item,event,client,remote_end=remote_end)
        if previous:
            remote_id=previous
        else:
            start=item.starts_at.astimezone(CLINIC_TZ)
            end=remote_end.astimezone(CLINIC_TZ)
            result=call('book',[event,UNIT_ID,client,start.strftime('%Y-%m-%d'),start.strftime('%H:%M:%S'),
                               end.strftime('%Y-%m-%d'),end.strftime('%H:%M:%S'),0,additional,1])
            rows=result.get('bookings') if isinstance(result,dict) else None
            if not isinstance(rows,list) or len(rows)!=1 or as_bool(result.get('require_confirm')):
                raise SyncConflict('source_booking_not_confirmed')
            remote_id=int(rows[0]['id'])
        _verify_readback(call, remote_id, item, event, client, remote_end=remote_end)
        _record_source_link(item, remote_id, event, client, expected_state='sending')
        return {'result':'linked','source_booking_id':str(remote_id)}
    except Exception:
        Appointment.objects.filter(pk=pk,simplybook_sync_state='sending').update(simplybook_sync_state='review')
        raise


def _verify_readback(call, remote_id, item, event, client, *, remote_end=None):
    expected = copy(item)
    expected.ends_at = remote_end or item.simplybook_remote_ends_at or item.ends_at
    detail = call('getBookingDetails', [remote_id])
    if (not isinstance(detail, dict) or str(detail.get('id')) != str(remote_id)
            or not _same_booking(detail, expected, event, client)):
        raise SyncConflict('source_booking_readback_mismatch')


def _record_source_link(item, remote_id, event, client, *, expected_state):
    with transaction.atomic():
        locked = Appointment.objects.select_for_update().get(pk=item.pk)
        schedule_fields = ('starts_at', 'ends_at', 'staff_id', 'customer_id', 'service_id', 'status')
        if (locked.simplybook_sync_state != expected_state or locked.simplybook_booking_id
                or locked.simplybook_event_id != str(event) or locked.simplybook_client_id != str(client)
                or any(getattr(locked, field) != getattr(item, field) for field in schedule_fields)):
            raise SyncConflict('local_booking_changed_during_write')
        duplicates = Appointment.objects.exclude(pk=item.pk).filter(
            models.Q(idempotency_key=f'simplybook-{remote_id}') | models.Q(simplybook_booking_id=str(remote_id))
        )
        if duplicates.exists():
            raise SyncConflict('source_booking_already_imported')
        locked.simplybook_booking_id = str(remote_id)
        locked.simplybook_sync_state = 'linked'
        locked.status = 'confirmed'
        locked.save(update_fields=['simplybook_booking_id', 'simplybook_sync_state', 'status', 'updated_at'])


def reconcile_existing(pk, *, apply=False, call=None):
    """Read the source after an uncertain write. Apply records the link locally."""
    item = Appointment.objects.select_related('customer', 'service', 'staff').get(pk=pk)
    if item.simplybook_booking_id and item.simplybook_sync_state == 'linked':
        return {'result': 'already_linked'}
    if item.simplybook_sync_state != 'review' or not item.simplybook_client_id:
        raise SyncConflict('review_with_known_source_client_required')
    call = call or session()
    event = _verify_catalog(call, item)
    if str(event) != item.simplybook_event_id:
        raise SyncConflict('source_service_mismatch')
    client = _get_client(call, item.customer, apply=False)
    if str(client) != item.simplybook_client_id:
        raise SyncConflict('linked_client_not_verified')
    day = item.starts_at.astimezone(CLINIC_TZ).date().isoformat()
    end_day = item.ends_at.astimezone(CLINIC_TZ).date().isoformat()
    rows = call('getBookings', [{'date_from': day, 'date_to': end_day, 'booking_type': 'non_cancelled'}])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SyncConflict('unexpected_bookings_shape')
    expected = copy(item)
    expected.ends_at = item.simplybook_remote_ends_at or item.ends_at
    matches = [row for row in rows if _same_booking(row, expected, event, client)]
    if not matches:
        return {'result': 'no_confirmed_remote_booking'}
    if len(matches) != 1:
        raise SyncConflict('duplicate_source_bookings')
    raw_id = str(matches[0].get('id') or '')
    if not raw_id.isdecimal() or int(raw_id) <= 0:
        raise SyncConflict('invalid_source_booking_id')
    remote_id = int(raw_id)
    _verify_readback(call, remote_id, item, event, client)
    if not apply:
        return {'result': 'confirmed_remote_booking'}
    _record_source_link(item, remote_id, event, client, expected_state='review')
    return {'result': 'linked', 'source_booking_id': str(remote_id)}
