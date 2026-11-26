"""Controlled, source-first creation of a single existing local Ariane booking.

No automatic retries after an uncertain remote write. Only explicit, reviewed
service mappings are accepted. The importer preserves the local UUID and key.
"""
import os
import logging
import re
from datetime import UTC
from django.db import transaction
from django.utils import timezone
from .clinical_time import CLINIC_TZ, parse_appointment_start
from .models import Appointment, SimplyBookClientLink
from .customer_identity import normalize_name, normalize_email, normalize_phone
from .management.commands.simplybook_import import rpc, LOGIN_URL, ADMIN_URL, as_bool

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

class SyncConflict(ValueError):
    pass

def session():
    company = os.getenv('SIMPLYBOOK_COMPANY_LOGIN','').strip()
    user = os.getenv('SIMPLYBOOK_USER_LOGIN','').strip()
    credential = (os.getenv('SIMPLYBOOK_API_USER_KEY') or os.getenv('SIMPLYBOOK_USER_PASSWORD') or '').strip()
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
            # Explicitly recorded returning customers are known. Web bookings
            # capture this question; other routes may only have a default false.
            if item.returning_customer or item.source == 'web':
                answer = 'Ja' if item.returning_customer else 'Nein'
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

def _verify_availability(call,item,event,client):
    day = item.starts_at.astimezone(CLINIC_TZ).date().isoformat()
    end_day = item.ends_at.astimezone(CLINIC_TZ).date().isoformat()
    bookings=call('getBookings',[{'date_from':day,'date_to':end_day,'booking_type':'non_cancelled'}])
    if not isinstance(bookings,list):
        raise SyncConflict('unexpected_bookings_shape')
    exact=[r for r in bookings if client and _same_booking(r,item,event,client)]
    if len(exact)>1:
        raise SyncConflict('duplicate_source_bookings')
    if exact:
        return int(exact[0]['id'])
    for row in bookings:
        if str(row.get('unit_id'))!=str(UNIT_ID):
            continue
        start=_dt(row.get('start_date') or row.get('start_date_time'))
        end=_dt(row.get('end_date') or row.get('end_date_time'))
        if start is None or end is None or start < item.ends_at and end > item.starts_at:
            raise SyncConflict('source_booking_conflict')
    matrix=call('getStartTimeMatrix',[day,day,event,UNIT_ID,1])
    times=matrix.get(day) if isinstance(matrix,dict) else None
    if not isinstance(times,list) or item.starts_at.astimezone(CLINIC_TZ).strftime('%H:%M') not in [str(t)[:5] for t in times]:
        raise SyncConflict('source_slot_unavailable')
    # Verify the entire local reserved duration, not just the remote service's
    # shorter default. The source admin booking also validates the supplied end.
    reserved=call('getReservedTimeIntervals',[day,end_day,event,UNIT_ID,1])
    if not isinstance(reserved,dict):
        raise SyncConflict('unexpected_reserved_shape')
    for row in reserved.get(day,[]):
        for interval in row.get('reserved_time',[]):
            start=_dt(day+' '+str(interval.get('from','')))
            finish=_dt(day+' '+str(interval.get('to','')))
            if start is None or finish is None or start < item.ends_at and finish > item.starts_at:
                raise SyncConflict('source_reserved_interval_conflict')
    return None

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
    previous=_verify_availability(call,item,event,client)
    if not apply:
        return {'result':'preflight_ok','existing_source_booking':bool(previous),'source_client_exists':bool(client)}
    # Serialize the claim before any booking mutation. A crash or timeout
    # must not permit an automatic second book() request.
    with transaction.atomic():
        locked=Appointment.objects.select_for_update().get(pk=pk)
        if (locked.simplybook_booking_id or locked.simplybook_sync_state or
            locked.starts_at!=item.starts_at or locked.ends_at!=item.ends_at or
            locked.customer_id!=item.customer_id or locked.staff_id!=item.staff_id or
            locked.service_id!=item.service_id or locked.status!=item.status):
            raise SyncConflict('local_booking_changed')
        locked.simplybook_sync_state='sending'
        locked.simplybook_event_id=str(event)
        locked.save(update_fields=['simplybook_sync_state','simplybook_event_id'])
    try:
        client=_get_client(call,item.customer,apply=True)
        Appointment.objects.filter(pk=pk,simplybook_sync_state='sending').update(simplybook_client_id=str(client))
        previous=_verify_availability(call,item,event,client)
        if previous:
            remote_id=previous
        else:
            start=item.starts_at.astimezone(CLINIC_TZ)
            end=item.ends_at.astimezone(CLINIC_TZ)
            result=call('book',[event,UNIT_ID,client,start.strftime('%Y-%m-%d'),start.strftime('%H:%M:%S'),
                               end.strftime('%Y-%m-%d'),end.strftime('%H:%M:%S'),0,additional,1])
            rows=result.get('bookings') if isinstance(result,dict) else None
            if not isinstance(rows,list) or len(rows)!=1 or result.get('require_confirm'):
                raise SyncConflict('source_booking_not_confirmed')
            remote_id=int(rows[0]['id'])
        detail=call('getBookingDetails',[remote_id])
        if not isinstance(detail,dict) or str(detail.get('id'))!=str(remote_id) or not _same_booking(detail,item,event,client):
            raise SyncConflict('source_booking_readback_mismatch')
        with transaction.atomic():
            locked=Appointment.objects.select_for_update().get(pk=pk)
            if locked.starts_at!=item.starts_at or locked.ends_at!=item.ends_at or locked.customer_id!=item.customer_id or locked.status!=item.status:
                raise SyncConflict('local_booking_changed_during_write')
            if Appointment.objects.filter(idempotency_key=f'simplybook-{remote_id}').exclude(pk=pk).exists():
                raise SyncConflict('source_booking_already_imported')
            locked.simplybook_booking_id=str(remote_id)
            locked.simplybook_sync_state='linked'
            locked.save(update_fields=['simplybook_booking_id','simplybook_sync_state'])
        return {'result':'linked','source_booking_id':str(remote_id)}
    except Exception:
        Appointment.objects.filter(pk=pk,simplybook_sync_state='sending').update(simplybook_sync_state='review')
        raise
