"""API for the bundled staff workspace. Desktop routes retain their existing contracts."""

import base64
import binascii
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Prefetch, Q, Count
from django.http import FileResponse, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .app_admin_api import _day_bounds, _private, _service_payload
from .calendar_admin_api import _block_payload
from .doctor_views import _save_availability, _save_weekly, _time
from .emails import send_customer_booking_email
from .internal_api import _patient_path
from .patient_uploads import save_patient_upload, PatientUploadError
from .models import (
    Appointment, BlockedPeriod, Customer, DailyAvailabilityOverride, DoctorPatientAccess,
    MobileStaffCancellation, MobileStaffCommand, PatientRecord, Service, StaffMember, WorkingHour, OfficeIntakeForm,
)
from .intake_forms import build_intake_pdf, confirm_form_link
from .notifications import appointment_snapshot, notify_admin_changed, notify_admin_created
from .services import effective_working_ranges
from .simplybook_writeback import enabled as simplybook_write_enabled, source_id as simplybook_source_id, write_existing_booking, SourceConflict, SourceUnavailable
from .patient_identity_review import possible_duplicate_pairs
from .patient_identity_views import process_decision

logger = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _verify(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None, 401
    origin = getattr(settings, 'MOBILE_STAFF_IDENTITY_ORIGIN', 'https://app.a-esthetic.de')
    remote = Request(
        f'{origin}/api/mobile/staff/session/',
        headers={'Authorization': header, 'Accept': 'application/json'},
    )
    try:
        with build_opener(NoRedirect).open(remote, timeout=5) as response:
            payload = json.loads(response.read(8192))
    except HTTPError as exc:
        return None, exc.code if exc.code in (401, 403) else 503
    except (URLError, TimeoutError, ValueError):
        return None, 503
    if not isinstance(payload, dict) or not payload.get('id') or payload.get('role') not in ('admin', 'doctor'):
        return None, 403
    return payload, 200


def _providers(actor):
    qs = StaffMember.objects.filter(active=True).order_by('sort_order', 'display_name')
    if actor['role'] == 'doctor':
        qs = qs.filter(role='doctor', display_name__iexact='Qamar Hameed')
    return qs


def _people(actor, providers):
    qs = Customer.objects.all()
    if actor['role'] == 'doctor':
        qs = qs.filter(
            Q(pk__in=Appointment.objects.filter(staff__in=providers).values('customer_id'))
            | Q(pk__in=DoctorPatientAccess.objects.filter(staff__in=providers).values('customer_id'))
        )
    return qs


def _records(actor, person, providers):
    records = person.patient_records.all()
    if actor['role'] == 'doctor':
        records = records.filter(
            Q(appointment__staff__in=providers)
            | Q(uploaded_by__username=f"aplus_app_admin_{actor['id']}")
            | Q(source='mobile_staff', metadata__actor_id=actor['id'])
            | Q(source__in=['botoxbogen', 'a_esthetic_app'])
        )
    return records


def _person(person):
    return {'id': person.pk, 'name': person.full_name, 'email': person.email, 'phone': person.phone}


def _appointment(item):
    start = timezone.localtime(item.starts_at)
    end = timezone.localtime(item.ends_at)
    return {
        'id': item.pk, 'customer_id': item.customer_id, 'customer_name': item.customer.full_name,
        'staff_id': item.staff_id, 'staff_name': item.staff.display_name, 'service_id': item.service_id,
        'service_name': item.service.name, 'start_at': start.isoformat(), 'end_at': end.isoformat(),
        'date': start.date().isoformat(), 'start': start.strftime('%H:%M'), 'end': end.strftime('%H:%M'),
        'status': item.status, 'notes': item.notes_customer, 'revision': item.updated_at.isoformat(),
        'source_managed': (item.idempotency_key or '').startswith('simplybook-'),
        'source_editable': bool(simplybook_source_id(item)) and item.status != 'cancelled' and simplybook_write_enabled(),
        'management_system': 'SimplyBook' if (item.idempotency_key or '').startswith('simplybook-') else 'Book',
        'credit_pending': hasattr(item, 'mobile_cancellation') and item.mobile_cancellation.completed_at is None,
    }


def _block(item, editable):
    # SimplyBook note sync stores its source identifier after an invisible
    # separator. This is read-only provenance, NOT permission to change source.
    imported = (item.reason or '').count('\u2063') >= 2
    payload = _block_payload(item)
    if imported:
        payload['text'] = payload['text'].split('\u2063', 1)[0].strip()
    return payload | {
        'editable': editable and not imported,
        'source_managed': imported,
        'management_system': 'SimplyBook' if imported else 'Book',
        'start_at': timezone.localtime(item.starts_at).isoformat(),
        'end_at': timezone.localtime(item.ends_at).isoformat(),
    }


def _appointments(providers):
    return Appointment.objects.filter(staff__in=providers).select_related(
        'customer', 'staff', 'service', 'mobile_cancellation',
    )


def _date(value):
    try:
        day = parse_date(str(value or ''))
    except ValueError:
        day = None
    if day is None or abs((day - timezone.localdate()).days) > 730:
        raise ValidationError('Datum außerhalb des zulässigen Bereichs.')
    return day


def _calendar(request, providers):
    start = _date(request.GET.get('start'))
    count = int(request.GET.get('days', '1'))
    if count not in (1, 7):
        raise ValidationError('Ungültiger Zeitraum.')
    days = [start + timedelta(days=offset) for offset in range(count)]
    lower = _day_bounds(start)[0]
    upper = _day_bounds(days[-1])[1]
    working = Prefetch('working_hours', queryset=WorkingHour.objects.filter(active=True), to_attr='mobile_hours')
    staff = list(providers.prefetch_related(working))
    overrides = {
        (row.staff_id, row.date): row for row in
        DailyAvailabilityOverride.objects.filter(staff__in=providers, date__range=(start, days[-1]))
    }
    availability = []
    for day in days:
        for person in staff:
            override = overrides.get((person.pk, day))
            ranges = override.ranges() if override else [
                (row.start_time, row.end_time) for row in person.mobile_hours if row.weekday == day.weekday()
            ]
            availability.append({
                'date': day.isoformat(), 'staff_id': person.pk, 'override': bool(override),
                'ranges': [{'start': a.strftime('%H:%M'), 'end': b.strftime('%H:%M')} for a, b in ranges],
            })
    blocks = list(BlockedPeriod.objects.filter(staff__in=providers, starts_at__lt=upper, ends_at__gt=lower))
    editable = set(MobileStaffCommand.objects.filter(action='block', object_id__in=[row.pk for row in blocks])
                   .values_list('object_id', flat=True))
    return _private({
        'ok': True, 'availability': availability,
        'appointments': [_appointment(item) for item in _appointments(providers)
                         .filter(starts_at__lt=upper, ends_at__gt=lower).exclude(status='cancelled')],
        'blocks': [_block(item, item.pk in editable) for item in blocks],
    })


def _catalog(providers):
    staff = providers.prefetch_related('working_hours', 'services')
    return _private({
        'ok': True,
        'providers': [{
            'id': item.pk, 'name': item.display_name, 'role': item.role,
            'source_managed': item.display_name.startswith('A+ Esthetic (SimplyBook #'),
            'management_system': ('SimplyBook' if item.display_name.startswith('A+ Esthetic (SimplyBook #') else 'Book'),
            'services': [service.pk for service in item.services.all() if service.active],
            'working_hours': [
                {'weekday': row.weekday, 'start': row.start_time.strftime('%H:%M'), 'end': row.end_time.strftime('%H:%M')}
                for row in item.working_hours.all() if row.active
            ],
        } for item in staff],
        'services': [
            _service_payload(item) | {
                'source_managed': item.slug.startswith('simplybook-event-'),
                'management_system': 'SimplyBook' if item.slug.startswith('simplybook-event-') else 'Book',
            }
            for item in Service.objects.filter(
                staff_members__in=providers).distinct().order_by('sort_order', 'name')
        ],
    })


def _record_file(actor, providers, person, record_id):
    record = _records(actor, person, providers).filter(public_id=record_id).first()
    if not record or not record.stored_name:
        return _private({'ok': False, 'error': 'not_found'}, 404)
    path = _patient_path(record.stored_name)
    if not path.is_file():
        return _private({'ok': False, 'error': 'not_found'}, 404)
    response = FileResponse(path.open('rb'), as_attachment=True, filename=record.original_name,
                            content_type='application/octet-stream')
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _read(request, actor, providers, action, ident, record_id):
    if action == 'calendar':
        return _calendar(request, providers)
    if action == 'catalog':
        return _catalog(providers)
    items = _appointments(providers)
    if action == 'overview':
        today, tomorrow = _day_bounds(timezone.localdate())
        active = items.exclude(status='cancelled')
        daily = active.filter(starts_at__gte=today, starts_at__lt=tomorrow)
        upcoming = active.filter(starts_at__gte=timezone.now())
        counts = dict(daily.values('staff_id').annotate(total=Count('pk')).values_list('staff_id','total'))
        return _private({'ok': True, 'today': daily.count(), 'upcoming_count': upcoming.count(),
                         'patient_count': _people(actor, providers).count(), 'provider_count': providers.count(),
                         'provider_today': [{'id': p.pk, 'name': p.display_name, 'count': counts.get(p.pk,0)} for p in providers],
                         **({'intake_review_count': OfficeIntakeForm.objects.filter(status='review').count()} if actor['role']=='admin' else {}),
                         'upcoming': [_appointment(row) for row in upcoming.order_by('starts_at')[:12]]})
    query = request.GET.get('q', '').strip()[:100]
    page = min(10000, max(1, int(request.GET.get('page', '1'))))
    offset = (page - 1) * 30
    if action == 'appointments':
        for term in query.split():
            items = items.filter(Q(customer__first_name__icontains=term) |
                                 Q(customer__last_name__icontains=term) | Q(service__name__icontains=term))
        rows = list(items.order_by('-starts_at', '-pk')[offset:offset+31])
        return _private({'ok': True, 'items': [_appointment(item) for item in rows[:30]], 'has_more': len(rows) > 30})
    people = _people(actor, providers)
    if action == 'patients':
        for term in query.split():
            people = people.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term) |
                                   Q(email__icontains=term) | Q(phone__icontains=term))
        rows = list(people.order_by('last_name', 'first_name', 'pk')[offset:offset+31])
        return _private({'ok': True, 'items': [_person(row) for row in rows[:30]], 'has_more': len(rows) > 30})
    person = people.filter(pk=ident).first()
    if not person:
        return _private({'ok': False, 'error': 'not_found'}, 404)
    if action == 'visit':
        if actor['role'] != 'admin':
            return _private({'ok': False, 'error': 'admin_required'}, 403)
        visit = items.filter(customer=person, public_id=record_id).first()
        if not visit:
            return _private({'ok': False, 'error': 'not_found'}, 404)
        return _private({'ok': True, 'visit': _appointment(visit) | {'public_id': str(visit.public_id)}})
    if action == 'record':
        return _record_file(actor, providers, person, record_id)
    return _private({
        'ok': True, 'patient': _person(person) | ({'first_name': person.first_name, 'last_name': person.last_name,
                                     'date_of_birth': person.date_of_birth.isoformat() if person.date_of_birth else None}
                                    if actor['role'] == 'admin' else {}),
        'records': [{
            'id': str(item.public_id), 'title': item.title, 'note': item.note,
            'date': item.created_at.isoformat(), 'has_file': item.has_file, 'filename': item.original_name,
            'kind': item.kind, 'mime_type': item.mime_type, 'source': item.source,
        } for item in _records(actor, person, providers).order_by('-created_at', '-pk')[offset:offset+31]][:30],
        'has_more': _records(actor, person, providers).count() > offset+30,
        'appointments': [_appointment(row) | {'public_id': str(row.public_id)} for row in items.filter(customer=person).order_by('-starts_at')[:20]],
    })

def _forms(request, actor, action, ident):
    if actor['role'] != 'admin':
        return _private({'ok': False, 'error': 'admin_required'}, 403)
    forms = OfficeIntakeForm.objects.select_related('customer','record')
    if request.method == 'GET' and action == 'forms':
        query = request.GET.get('q','').strip()[:100]
        status = request.GET.get('status','')
        for term in query.split():
            forms = forms.filter(Q(payload__identity__first_name__icontains=term) |
                                 Q(payload__identity__last_name__icontains=term) |
                                 Q(payload__identity__email__icontains=term) |
                                 Q(payload__identity__phone__icontains=term))
        if status:
            if status not in {'linked','review'}: raise ValueError('Invalid status')
            forms = forms.filter(status=status)
        for field, lookup in [('from','submitted_at__date__gte'),('to','submitted_at__date__lte')]:
            if request.GET.get(field):
                day = parse_date(request.GET[field])
                if day is None: raise ValueError('Invalid date')
                forms = forms.filter(**{lookup:day})
        page = max(1,min(10000,int(request.GET.get('page','1'))))
        rows = list(forms.defer('signature_png').order_by('-submitted_at','-pk')[(page-1)*30:page*30+1])
        def item(f):
            identity=f.payload.get('identity') or {}
            return {'id':f.pk,'name':' '.join(str(identity.get(k,'')) for k in ('first_name','last_name')).strip(),
                    'email':identity.get('email',''),'created_at':f.submitted_at.isoformat(),'status':f.status}
        return _private({'ok':True,'items':[item(f) for f in rows[:30]],'has_more':len(rows)>30})
    if request.method == 'GET' and action in {'form','form-pdf'}:
        form = forms.filter(pk=ident).first()
        if not form: return _private({'ok':False,'error':'not_found'},404)
        if action == 'form-pdf':
            result = HttpResponse(build_intake_pdf(form),content_type='application/pdf')
            result['Cache-Control']='private, no-store, max-age=0'
            result['Content-Disposition']='attachment; filename="aufnahmebogen.pdf"'
            return result
        return _private({'ok':True,'submission':{'id':form.pk,'identity':form.payload.get('identity',{}),
            'answers':form.payload.get('answers',{}),'consent_text':form.payload.get('consent_text',''),
            'signature_png':form.signature_png,'created_at':form.submitted_at.isoformat(),'status':form.status,
            'book_customer_id':form.customer_id,'book_record_id':str(form.record.public_id) if form.record_id else ''}})
    if request.method == 'POST' and action == 'form-link':
        if len(request.body)>8000: raise ValueError('Invalid form')
        data=json.loads(request.body)
        if not isinstance(data,dict) or data.get('confirmed_same_patient') is not True:
            return _private({'ok':False,'error':'identity_verification_required'},409)
        if not forms.filter(pk=ident).exists() or not Customer.objects.filter(pk=int(data.get('customer_id',0))).exists():
            return _private({'ok':False,'error':'not_found'},404)
        # Retain the verified external reviewer in the same private audit
        # identity used by Book SSO; never grant this shadow login privileges.
        reviewer,created=get_user_model().objects.get_or_create(username=f"aplus_app_admin_{int(actor['id'])}")
        if created:
            reviewer.set_unusable_password();reviewer.save(update_fields=['password'])
        try:
            form=confirm_form_link(ident,int(data['customer_id']),reviewer)
        except ValueError as exc:
            return _private({'ok':False,'error':'identity_review_conflict','message':str(exc)},409)
        return _private({'ok':True,'customer_id':form.customer_id,'status':form.status})
    return _private({'ok':False,'error':'method_not_allowed'},405)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def workspace(request, action, ident=None, record_id=None):
    actor, status = _verify(request)
    if not actor:
        return _private({'ok': False, 'error': 'staff_access_unavailable' if status == 503 else 'staff_required'}, status)
    providers = _providers(actor)
    if actor['role'] == 'doctor' and providers.count() != 1:
        return _private({'ok': False, 'error': 'doctor_not_configured'}, 403)
    try:
        if action in {'forms','form','form-pdf','form-link'}:
            return _forms(request,actor,action,ident)
        if action == 'identity-review':
            if actor['role'] != 'admin':
                return _private({'ok': False, 'error': 'admin_required'}, 403)
            if request.method == 'GET':
                rows = possible_duplicate_pairs(limit=150)
                def identity(person):
                    return _person(person) | {
                        'first_name': person.first_name, 'last_name': person.last_name,
                        'date_of_birth': person.date_of_birth.isoformat() if person.date_of_birth else None,
                    }
                return _private({'ok': True, 'items': [{
                    'left': identity(pair['left']), 'right': identity(pair['right']),
                    'reason': pair['reason'], 'fingerprint': pair['fingerprint'],
                } for pair in rows]})
            if len(request.body) > 8000:
                raise ValueError('Invalid review')
            data = json.loads(request.body)
            if not isinstance(data, dict):
                raise ValueError('Invalid review')
            try:
                review = process_decision(data, aesthetic_actor_id=int(actor['id']))
            except ValueError as exc:
                return _private({'ok': False, 'error': 'identity_review_conflict', 'message': str(exc)}, 409)
            return _private({'ok': True, 'id': review.pk})
        if request.method == 'GET' and action in {'calendar', 'catalog', 'overview', 'appointments', 'patients', 'patient', 'record', 'visit'}:
            return _read(request, actor, providers, action, ident, record_id)
        if request.method == 'POST' and action in {'appointment', 'block', 'availability', 'service', 'record-note', 'record-upload'}:
            return _mutate(request, actor, providers, action)
    except (ValidationError, TypeError, ValueError, OverflowError) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Die Eingaben sind ungültig.'
        return _private({'ok': False, 'error': 'invalid_request', 'message': message}, 400)
    return _private({'ok': False, 'error': 'method_not_allowed'}, 405)


class CommandConflict(ValueError):
    pass


def _notify(callback, *args):
    try:
        callback(*args)
    except Exception:
        logger.exception('Mobile staff appointment notification failed: appointment=%s', args[0].pk)


def _slot(date, clock):
    day = _date(date)
    value = _time(clock)
    if value is None:
        raise ValidationError('Bitte eine Uhrzeit im 15-Minuten-Raster eingeben.')
    wall = datetime.combine(day, value)
    zone = timezone.get_current_timezone()
    aware = timezone.make_aware(wall, zone)
    if aware.utcoffset() != aware.replace(fold=1).utcoffset() or aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall:
        raise ValidationError('Diese Uhrzeit ist wegen der Zeitumstellung nicht eindeutig.')
    return aware


def _check_schedule(staff, start, end):
    day = start.date()
    tz = timezone.get_current_timezone()
    ranges, _ = effective_working_ranges(staff, day)
    if not any(timezone.make_aware(datetime.combine(day, a), tz) <= start
               and end <= timezone.make_aware(datetime.combine(day, b), tz) for a, b in ranges):
        raise CommandConflict('Die gewählte Zeit liegt außerhalb der Arbeitszeit.')
    if BlockedPeriod.objects.filter(staff=staff, starts_at__lt=end, ends_at__gt=start).exclude(
        reason__startswith='[NOTE]',
    ).exists():
        raise CommandConflict('Die gewählte Zeit ist gesperrt.')


def _save_synced_appointment(data, actor, item):
    """A staff-only *reschedule or cancellation*, confirmed in SimplyBook first.

    Never alter source service/provider/client via generic Book fields. Imported
    provider represents multiple actual source units; remote unit_id is used.
    """
    if actor['role'] != 'admin':
        raise PermissionError
    if not simplybook_write_enabled():
        raise CommandConflict('SimplyBook-Termine bleiben bis zur abgesicherten Freigabe schreibgeschützt.')
    revision=parse_datetime(str(data.get('revision') or ''))
    if revision != item.updated_at:
        raise CommandConflict('Der Termin wurde zwischenzeitlich geändert. Bitte neu laden.')
    if item.status == 'cancelled':
        raise CommandConflict('Der Termin ist bereits abgesagt.')
    operation=data.get('operation')
    if operation not in ('update','cancel'):
        raise CommandConflict('Unzulässige SimplyBook-Aktion.')
    if operation=='cancel':
        try:
            write_existing_booking(item,operation='cancel')
        except (SourceConflict,SourceUnavailable) as exc:
            raise CommandConflict(str(exc)) from exc
        item.status='cancelled'
        item.save(update_fields=['status','updated_at'])
        return item.pk

    if (int(data.get('staff_id') or 0)!=item.staff_id or
        int(data.get('service_id') or 0)!=item.service_id or
        int(data.get('customer_id') or 0)!=item.customer_id or
        str(data.get('status') or item.status)!=item.status or
        ('notes' in data and str(data.get('notes') or '')!=str(item.notes_customer or ''))):
        raise CommandConflict('Für SimplyBook sind derzeit nur Terminzeit und Stornierung freigegeben.')
    start=_slot(data.get('date'),data.get('start'))
    end=start+(item.ends_at-item.starts_at)
    if start==item.starts_at:
        return item.pk
    previous=appointment_snapshot(item)
    try:
        write_existing_booking(item,operation='reschedule',start=start,end=end)
    except (SourceConflict,SourceUnavailable) as exc:
        raise CommandConflict(str(exc)) from exc
    item.starts_at=start
    item.ends_at=end
    for field in ('reminder_24h_sent_at','reminder_1h_sent_at',
                  'reminder_1h_admin_email_sent_at','reminder_1h_admin_push_sent_at'):
        setattr(item,field,None)
    item.save(update_fields=['starts_at','ends_at','updated_at','reminder_24h_sent_at',
                            'reminder_1h_sent_at','reminder_1h_admin_email_sent_at',
                            'reminder_1h_admin_push_sent_at'])
    transaction.on_commit(lambda: _notify(notify_admin_changed,item,previous))
    return item.pk


def _save_appointment(data, actor, providers, previous_item):
    operation = data.get('operation')
    item = previous_item
    if operation not in {'create', 'update', 'cancel'} or bool(item) == (operation == 'create'):
        raise ValidationError('Ungültige Terminaktion.')
    if item:
        if (item.idempotency_key or '').startswith('simplybook-'):
            return _save_synced_appointment(data,actor,item)
        if item.status == 'cancelled':
            if operation == 'cancel':
                return item.pk
            raise CommandConflict('Der Termin ist bereits abgesagt.')
        revision = parse_datetime(str(data.get('revision') or ''))
        if revision != item.updated_at:
            raise CommandConflict('Der Termin wurde zwischenzeitlich geändert. Bitte neu laden.')
    if operation == 'cancel':
        item.status = 'cancelled'
        item.save(update_fields=['status', 'updated_at'])
        MobileStaffCancellation.objects.get_or_create(
            booking_public_id=item.public_id, defaults={'appointment': item},
        )
        return item.pk

    staff = providers.filter(pk=int(data['staff_id'])).first()
    customer = _people(actor, providers).filter(pk=int(data['customer_id'])).first()
    service = Service.objects.filter(pk=int(data['service_id']), staff_members=staff).first() if staff else None
    if not staff or not customer or not service:
        raise ValidationError('Patient, Behandlung oder Behandler ist nicht verfügbar.')
    if staff.display_name.startswith('A+ Esthetic (SimplyBook #') or service.slug.startswith('simplybook-event-'):
        raise CommandConflict('Dieser Behandler oder diese Behandlung stammt aus SimplyBook. Bitte Reservierungen dort verwalten.')
    start = _slot(data.get('date'), data.get('start'))
    previous = appointment_snapshot(item) if item else None
    schedule_changed = not item or item.starts_at != start or item.service_id != service.pk or item.staff_id != staff.pk
    end = start + timedelta(minutes=service.duration_minutes + service.buffer_minutes) if schedule_changed else item.ends_at
    if item and item.customer_id != customer.pk:
        raise CommandConflict('Der Patient eines bestehenden Termins kann hier nicht geändert werden.')
    if schedule_changed:
        if item and item.service_id != service.pk:
            raise CommandConflict('Eine Änderung der Behandlung erfordert die Prüfung des Behandlungspakets.')
        if not service.active or not service.bookable:
            raise CommandConflict('Die Behandlung ist derzeit nicht buchbar.')
        _check_schedule(staff, start, end)

    if not item:
        item = Appointment(
            customer=customer, source='admin', marketing_opt_in=False,
            returning_customer=Appointment.objects.filter(customer=customer).exists(),
            status='new' if actor['role'] == 'doctor' and service.requires_confirmation else 'confirmed',
        )
    status = data.get('status') if previous else item.status
    if status not in {'new', 'confirmed', 'completed', 'no_show'}:
        raise ValidationError('Ungültiger Terminstatus.')
    item.staff = staff
    item.service = service
    item.starts_at = start
    item.ends_at = end
    item.status = status
    if schedule_changed:
        for field in ('reminder_24h_sent_at', 'reminder_1h_sent_at', 'reminder_1h_admin_email_sent_at',
                      'reminder_1h_admin_push_sent_at'):
            setattr(item, field, None)
    try:
        item.full_clean()
    except ValidationError as exc:
        raise CommandConflict(' '.join(exc.messages)) from exc
    item.save()
    if previous:
        transaction.on_commit(lambda: _notify(notify_admin_changed, item, previous))
    else:
        if actor['role'] == 'admin':
            transaction.on_commit(lambda: _notify(send_customer_booking_email, item))
        transaction.on_commit(lambda: _notify(notify_admin_created, item))
    return item.pk


def _save_block(data, providers):
    staff = providers.filter(pk=int(data['staff_id'])).first()
    if not staff:
        raise ValidationError('Ungültiger Behandler.')
    if staff.display_name.startswith('A+ Esthetic (SimplyBook #'):
        raise CommandConflict('Dieser Kalender wird aus SimplyBook synchronisiert. Bitte Sperrzeiten direkt dort verwalten.')
    operation = data.get('operation')
    if operation not in {'create', 'update', 'delete'}:
        raise ValidationError('Ungültige Kalenderaktion.')
    item = None
    if operation != 'create':
        item = BlockedPeriod.objects.select_for_update().filter(pk=int(data['id']), staff=staff).first()
        if item and (item.reason or '').count('\u2063') >= 2:
            raise CommandConflict('Dieser Kalendereintrag wird über SimplyBook synchronisiert. Bitte direkt in SimplyBook ändern.')
        if not item or not MobileStaffCommand.objects.filter(action='block',object_id=item.pk).exists():
            raise CommandConflict('Dieser Eintrag wird in der Book-Verwaltung verwaltet. Bitte dort ändern.')
        if operation == 'delete':
            ident = item.pk
            item.delete()
            return ident
    start = _slot(data.get('date'), data.get('start'))
    end = _slot(data.get('date'), data.get('end'))
    text = str(data.get('text') or '').strip()[:120]
    is_note = data.get('kind') == 'note'
    if start >= end or (is_note and not text):
        raise ValidationError('Bitte Zeitraum und Text prüfen.')
    if not is_note and _appointments(providers).filter(
        staff=staff, status__in=['new', 'confirmed'], starts_at__lt=end, ends_at__gt=start,
    ).exists():
        raise CommandConflict('In diesem Zeitraum gibt es bereits einen Termin.')
    prefix = '[NOTE][STAFF]' if is_note else '[BLOCKNOTE][STAFF]'
    if not item:
        item = BlockedPeriod(staff=staff)
    item.starts_at, item.ends_at, item.reason = start, end, f'{prefix} {text or "Gesperrt"}'
    item.full_clean()
    item.save()
    return item.pk


def _save_hours(data, providers):
    staff = providers.filter(pk=int(data['staff_id'])).first()
    if not staff or data.get('operation') not in {'daily', 'weekly', 'reset'}:
        raise ValidationError('Ungültige Verfügbarkeit.')
    if staff.display_name.startswith('A+ Esthetic (SimplyBook #'):
        raise CommandConflict('Diese Arbeitszeiten werden aus SimplyBook synchronisiert. Bitte direkt in SimplyBook ändern.')
    date = _date(data.get('date'))
    post = {**data, 'closed': 'on' if data.get('closed') is True else '', 'action': data['operation']}
    if data['operation'] == 'weekly':
        _save_weekly(staff, date.weekday(), post)
    else:
        _save_availability(staff, date, post)
    return staff.pk


def _save_service(data, actor):
    if actor['role'] != 'admin':
        raise PermissionError
    item = Service.objects.select_for_update().filter(pk=int(data['id'])).first()
    if not item:
        raise ValidationError('Behandlung nicht gefunden.')
    if item.slug.startswith('simplybook-event-'):
        raise CommandConflict('Diese Behandlung wird aus SimplyBook synchronisiert. Bitte direkt in SimplyBook ändern.')
    for field in ('name', 'description', 'price_label'):
        if field in data:
            setattr(item, field, str(data[field]).strip())
    for field in ('active', 'bookable', 'requires_confirmation'):
        if field in data and isinstance(data[field], bool):
            setattr(item, field, data[field])
    for field in ('duration_minutes', 'buffer_minutes'):
        if field in data:
            setattr(item, field, int(data[field]))
    if item.duration_minutes < 1 or item.duration_minutes + item.buffer_minutes > 720:
        raise ValidationError('Ungültige Dauer.')
    item.full_clean()
    item.save()
    return item.pk


def _mutate(request, actor, providers, action):
    try:
        if len(request.body) > (8 * 1024 * 1024 + 24000 if action == 'record-upload' else 24000):
            raise ValueError
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        key = UUID(str(data.pop('key', '')))
        fingerprint = hashlib.sha256(json.dumps([action, data], sort_keys=True).encode()).hexdigest()
    except (TypeError, ValueError):
        raise ValidationError('Ungültiger Auftrag.')
    try:
        with transaction.atomic():
            # Take provider locks in a stable order before touching appointments. Public
            # booking also locks the provider before checking its slot.
            lock_ids = []
            if 'staff_id' in data:
                lock_ids.append(int(data['staff_id']))
            ident = data.get('id')
            if action == 'appointment' and ident:
                original_staff = _appointments(providers).filter(pk=int(ident)).values_list('staff_id', flat=True).first()
                if not original_staff:
                    return _private({'ok': False, 'error': 'not_found'}, 404)
                lock_ids.append(original_staff)
            if set(lock_ids) != set(providers.filter(pk__in=lock_ids).order_by('pk').select_for_update().values_list('pk', flat=True)):
                return _private({'ok': False, 'error': 'not_found'}, 404)
            receipt, created = MobileStaffCommand.objects.get_or_create(
                actor_id=actor['id'], key=key, defaults={'fingerprint': fingerprint, 'action': action},
            )
            if not created:
                if receipt.fingerprint != fingerprint:
                    raise CommandConflict('Dieser Auftrag wurde bereits mit anderen Eingaben verwendet.')
                return _private({'ok': True, 'id': receipt.object_id, 'replayed': True})
            if action == 'appointment':
                item = _appointments(providers).select_for_update(of=('self',)).filter(pk=int(ident)).first() if ident else None
                if ident and (not item or item.staff_id not in lock_ids):
                    raise CommandConflict('Der Termin wurde zwischenzeitlich geändert. Bitte neu laden.')
                result = _save_appointment(data, actor, providers, item)
            elif action == 'block':
                result = _save_block(data, providers)
            elif action == 'availability':
                result = _save_hours(data, providers)
            elif action == 'service':
                result = _save_service(data, actor)
            else:
                person = _people(actor, providers).filter(pk=int(data['customer_id'])).first()
                if not person:
                    raise PermissionError
                if action == 'record-upload':
                    # Only the explicitly selected patient's authorized timeline.
                    filename = str(data.get('filename') or '').strip()
                    if not filename.lower().endswith('.pdf') or len(filename) > 200 or '/' in filename or '\\' in filename:
                        raise ValidationError('Nur PDF-Dateien sind zulässig.')
                    try:
                        content = base64.b64decode(str(data.get('base64') or ''), validate=True)
                    except (ValueError, binascii.Error):
                        raise ValidationError('Ungültige PDF-Datei.')
                    if not content.startswith(b'%PDF-') or not 0 < len(content) <= 6 * 1024 * 1024:
                        raise ValidationError('PDF-Datei darf maximal 6 MB groß sein.')
                    appointment = _appointments(providers).filter(customer=person).order_by('-starts_at').first() if actor['role'] == 'doctor' else None
                    try:
                        uploaded = save_patient_upload(user=None, customer=person,
                            files=[SimpleUploadedFile(filename, content, content_type='application/pdf')],
                            kind='document', appointment=appointment, shared=False, source='mobile_staff')[0]
                    except PatientUploadError:
                        raise ValidationError('Datei konnte nicht gespeichert werden.')
                    uploaded.metadata = {**uploaded.metadata, 'actor_id': actor['id']}
                    uploaded.save(update_fields=['metadata'])
                    receipt.object_id = uploaded.pk
                    receipt.save(update_fields=['object_id'])
                    return _private({'ok': True, 'id': uploaded.pk})
                note = str(data.get('note') or '').strip()
                title = str(data.get('title') or '').strip()
                if not note or len(note) > 6000 or not title or len(title) > 180:
                    raise ValidationError('Bitte Titel und Notiz prüfen.')
                item = PatientRecord.objects.create(
                    customer=person, kind='note', title=title, note=note, source='mobile_staff',
                    metadata={'actor_id': actor['id'], 'shared_with_customer': False},
                    appointment=_appointments(providers).filter(customer=person).order_by('-starts_at').first()
                    if actor['role'] == 'doctor' else None,
                )
                result = item.pk
            receipt.object_id = result
            receipt.save(update_fields=['object_id'])
    except CommandConflict as exc:
        return _private({'ok': False, 'error': 'conflict', 'message': str(exc)}, 409)
    except PermissionError:
        return _private({'ok': False, 'error': 'admin_required'}, 403)
    except KeyError as exc:
        raise ValidationError('Erforderliche Eingaben fehlen.') from exc
    return _private({'ok': True, 'id': result})
