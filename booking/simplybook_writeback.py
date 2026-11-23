"""Guarded SimplyBook administration write-back for a *single existing* booking.

Source is authoritative. Never commit a local edit before a verified remote change.
No patient contact, service catalogue, hours, notes, or source block writes here.
Remote errors are not retried automatically: a read-back/re-import is required to
avoid a duplicate or an unintended second modification.
"""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from .management.commands.simplybook_import import rpc, RpcError

LOGIN_URL = 'https://user-api.simplybook.me/login'
ADMIN_URL = 'https://user-api.simplybook.me/admin'
BERLIN = ZoneInfo('Europe/Berlin')


class SourceConflict(Exception):
    pass


class SourceUnavailable(Exception):
    pass


def enabled():
    return str(os.getenv('SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED', '')).lower() == 'true'


def source_id(appointment):
    key=str(appointment.idempotency_key or '')
    external=key[len('simplybook-'):] if key.startswith('simplybook-') else ''
    return int(external) if external.isdecimal() and int(external)>0 else None


def _session():
    if not enabled():
        raise SourceConflict('SimplyBook-Schreiben ist noch nicht für diese Praxis freigegeben.')
    company=(os.getenv('SIMPLYBOOK_COMPANY_LOGIN') or '').strip()
    user=(os.getenv('SIMPLYBOOK_USER_LOGIN') or '').strip()
    secret=(os.getenv('SIMPLYBOOK_API_USER_KEY') or os.getenv('SIMPLYBOOK_USER_PASSWORD') or '').strip()
    if not (company and user and secret):
        raise SourceUnavailable('SimplyBook-Zugang fehlt. Es wurde nichts geändert.')
    try:
        token=rpc(LOGIN_URL,'getUserToken',[company,user,secret],timeout=18)
    except (RpcError, OSError):
        raise SourceUnavailable('SimplyBook-Anmeldung nicht möglich. Es wurde nichts geändert.') from None
    if not token:
        raise SourceUnavailable('SimplyBook-Anmeldung fehlgeschlagen. Es wurde nichts geändert.')
    return {'X-Company-Login':company,'X-User-Token':token}


def _remote_call(method, params, headers):
    try:
        return rpc(ADMIN_URL,method,params,headers=headers,timeout=18)
    except (RpcError, OSError):
        raise SourceUnavailable('SimplyBook meldet einen Fehler. Bitte Termin neu laden und Status prüfen.') from None


def _remote_dt(value):
    try:
        text=str(value or '')[:19]
        return datetime.strptime(text,'%Y-%m-%d %H:%M:%S').replace(tzinfo=BERLIN)
    except (TypeError,ValueError):
        raise SourceConflict('SimplyBook liefert kein prüfbares Kalenderdatum.')


def _detail(external_id, headers):
    row=_remote_call('getBookingDetails',[external_id],headers)
    if not isinstance(row,dict) or str(row.get('id'))!=str(external_id):
        raise SourceConflict('SimplyBook-Buchung konnte nicht eindeutig gelesen werden.')
    return row


def _compare(item, remote):
    # Strict optimistic concurrency: refuse to overwrite external user edits
    # that the ten-minute importer has not yet mirrored.
    rs=_remote_dt(remote.get('start_date_time'))
    re=_remote_dt(remote.get('end_date_time'))
    local_start=timezone.localtime(item.starts_at,BERLIN)
    local_end=timezone.localtime(item.ends_at,BERLIN)
    if (abs((rs-local_start).total_seconds())>1 or
        abs((re-local_end).total_seconds())>1):
        raise SourceConflict('Termin wurde in SimplyBook geändert. Bitte neu synchronisieren.')
    if str(remote.get('event_id'))!=str(item.service.slug.removeprefix('simplybook-event-')):
        raise SourceConflict('Behandlung in SimplyBook wurde zwischenzeitlich geändert.')
    from .models import SimplyBookClientLink
    links=SimplyBookClientLink.objects.filter(customer=item.customer).values_list('external_client_id',flat=True)
    if str(remote.get('client_id')) not in set(links):
        raise SourceConflict('Patientenidentität in SimplyBook stimmt nicht überein.')
    if not (remote.get('is_confirmed') is True or
            str(remote.get('is_confirmed')).lower() in ('1','true')):
        raise SourceConflict('Der Termin ist in SimplyBook nicht mehr bestätigt.')
    return rs,re


def write_existing_booking(item, *, operation, start=None, end=None):
    """Return confirmed remote detail. Caller commits local changes only after this.

    Supported: reschedule preserving source provider, service and client, cancel.
    Creation and service/provider reassignment need a separate guarded workflow.
    """
    external_id=source_id(item)
    if not external_id:
        raise SourceConflict('Dieser Termin hat keine sichere SimplyBook-ID.')
    if operation not in ('reschedule','cancel'):
        raise SourceConflict('Diese SimplyBook-Aktion ist nicht freigegeben.')
    headers=_session()
    remote=_detail(external_id,headers)
    _compare(item,remote)
    # Do not silently discard SimplyBook custom fields or interfere with
    # paid invoices, deposits or payment/credit workflows.
    if (remote.get('invoice_id') not in (None,0,'0','') or
        remote.get('invoice_payment_received') not in (None,0,'0','',False) or
        remote.get('deposit_is_enabled') in (True,1,'1','true')):
        raise SourceConflict('Bezahlte oder fakturierte SimplyBook-Termine müssen dort verwaltet werden.')
    if operation=='reschedule' and remote.get('additional_fields') not in (None,{},[],''):
        raise SourceConflict('Dieser Termin besitzt zusätzliche SimplyBook-Felder und muss dort geändert werden.')
    if operation=='reschedule':
        if not start or not end or end<=start:
            raise SourceConflict('Ungültiger Terminzeitraum.')
        new_start=timezone.localtime(start,BERLIN)
        new_end=timezone.localtime(end,BERLIN)
        if (new_start.year<2020 or new_end-new_start>timedelta(hours=12)
                or new_start<=timezone.now().astimezone(BERLIN)):
            raise SourceConflict('Der neue Terminzeitraum ist ungültig.')
        if abs((new_end-new_start).total_seconds()-(item.ends_at-item.starts_at).total_seconds())>1:
            raise SourceConflict('Daueränderungen müssen separat in SimplyBook geprüft werden.')
        params=[
            external_id,int(remote['event_id']),int(remote['unit_id']),
            int(remote['client_id']),new_start.strftime('%Y-%m-%d'),
            new_start.strftime('%H:%M:%S'),new_end.strftime('%Y-%m-%d'),
            new_end.strftime('%H:%M:%S'),int(remote.get('client_time_offset') or 0),{},
        ]
        _remote_call('editBook',params,headers)
    else:
        result=_remote_call('cancelBooking',[external_id],headers)
        if result is not True and result!=1:
            raise SourceUnavailable('SimplyBook hat die Stornierung nicht bestätigt.')
    # A successful RPC is insufficient if it returns a false-positive response.
    verified=_detail(external_id,headers)
    if operation=='reschedule':
        actual_start=_remote_dt(verified.get('start_date_time'))
        actual_end=_remote_dt(verified.get('end_date_time'))
        if abs((actual_start-new_start).total_seconds())>1 or abs((actual_end-new_end).total_seconds())>1:
            raise SourceUnavailable('SimplyBook bestätigt noch nicht den neuen Zeitraum. Bitte Status prüfen.')
    elif verified.get('is_confirmed') in (True,1,'1','true','True'):
        raise SourceUnavailable('SimplyBook bestätigt die Stornierung noch nicht. Bitte Status prüfen.')
    return verified
