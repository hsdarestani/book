import base64
import binascii
import json
import mimetypes
import re
import secrets
import uuid
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Appointment, Customer, PatientRecord


def _error(code, message, status=400):
    return JsonResponse({'ok': False, 'error': code, 'message': message}, status=status)


def _authorized(request):
    expected = str(getattr(settings, 'PATIENT_SYNC_TOKEN', '') or '').strip()
    if not expected:
        return None
    provided = str(request.headers.get('X-Aesthetic-Patient-Sync') or '').strip()
    if not provided:
        authorization = str(request.headers.get('Authorization') or '').strip()
        if authorization.lower().startswith('bearer '):
            provided = authorization[7:].strip()
    return bool(provided) and secrets.compare_digest(provided, expected)


def _payload(request):
    if (request.content_type or '').split(';', 1)[0].strip().lower() == 'application/json':
        try:
            data = json.loads(request.body.decode('utf-8')) if request.body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None
    data = request.POST.dict()
    raw_metadata = data.get('metadata')
    if raw_metadata:
        try:
            parsed = json.loads(raw_metadata)
            data['metadata'] = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            data['metadata'] = {}
    return data


def _normalize_phone(value):
    return re.sub(r'\D+', '', str(value or ''))


def _find_customer(email, phone):
    if email:
        customer = Customer.objects.filter(email__iexact=email).order_by('pk').first()
        if customer:
            return customer
    normalized = _normalize_phone(phone)
    if normalized:
        for customer in Customer.objects.exclude(phone='').only('pk', 'phone', 'email', 'first_name', 'last_name'):
            if _normalize_phone(customer.phone) == normalized:
                return customer
    return None


def _patient_path(stored_name):
    root = Path(settings.PATIENT_FILES_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = (root / stored_name).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError('invalid_storage_path')
    return candidate


def _store_bytes(customer, original_name, content, mime_type=''):
    safe_name = Path(original_name or 'datei').name[:255]
    extension = Path(safe_name).suffix.lower()
    if extension not in settings.PATIENT_FILE_ALLOWED_EXTENSIONS:
        raise ValueError('file_type')
    if not content:
        raise ValueError('file_empty')
    if len(content) > settings.PATIENT_FILE_MAX_BYTES:
        raise ValueError('file_size')
    stored_name = f'{customer.pk}/{uuid.uuid4().hex}{extension}'
    destination = _patient_path(stored_name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    guessed = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
    return stored_name, safe_name, (mime_type or guessed)[:120], len(content)


def _parse_captured_at(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@csrf_exempt
@require_POST
def ingest_patient_record(request):
    auth = _authorized(request)
    if auth is None:
        return _error('integration_not_configured', 'Patientenakten-Synchronisation ist nicht konfiguriert.', 503)
    if not auth:
        return _error('unauthorized', 'Nicht autorisiert.', 401)

    data = _payload(request)
    if data is None:
        return _error('invalid_json', 'Ungültige Nutzdaten.')

    source = re.sub(r'[^a-zA-Z0-9_.:-]+', '-', str(data.get('source') or 'external').strip()).strip('-')[:60] or 'external'
    external_id = str(data.get('external_id') or '').strip()[:180]
    if external_id:
        existing = PatientRecord.objects.select_related('customer').filter(source=source, external_id=external_id).first()
        if existing:
            return JsonResponse({
                'ok': True,
                'created': False,
                'record_id': str(existing.public_id),
                'customer_id': existing.customer_id,
            })

    email = str(data.get('email') or '').strip().lower()[:254]
    phone = str(data.get('phone') or '').strip()[:40]
    first_name = str(data.get('first_name') or '').strip()[:80]
    last_name = str(data.get('last_name') or '').strip()[:80]
    full_name = str(data.get('full_name') or '').strip()
    if full_name and not (first_name or last_name):
        parts = full_name.split(None, 1)
        first_name = parts[0][:80]
        last_name = parts[1][:80] if len(parts) > 1 else ''

    customer = _find_customer(email, phone)
    if not customer:
        if not email or '@' not in email:
            return _error('patient_not_found', 'Für einen neuen Patienten ist eine gültige E-Mail-Adresse erforderlich.')
        customer = Customer.objects.create(
            first_name=first_name or 'Patient',
            last_name=last_name,
            email=email,
            phone=phone,
        )
    else:
        changed = []
        if first_name and customer.first_name != first_name:
            customer.first_name = first_name
            changed.append('first_name')
        if last_name and customer.last_name != last_name:
            customer.last_name = last_name
            changed.append('last_name')
        if phone and customer.phone != phone:
            customer.phone = phone
            changed.append('phone')
        if email and customer.email.lower() != email:
            customer.email = email
            changed.append('email')
        if changed:
            customer.save(update_fields=[*changed, 'updated_at'])

    kind = str(data.get('kind') or 'form').strip()
    if kind not in {value for value, _ in PatientRecord.KIND}:
        return _error('invalid_kind', 'Ungültiger Akten-Typ.')
    title = str(data.get('title') or '').strip()[:180]
    note = str(data.get('note') or '').strip()[:20000]
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    try:
        if len(json.dumps(metadata, ensure_ascii=False)) > 65536:
            return _error('metadata_too_large', 'Metadaten sind zu groß.')
    except (TypeError, ValueError):
        return _error('invalid_metadata', 'Metadaten müssen JSON-kompatibel sein.')

    appointment = None
    raw_appointment_id = str(data.get('appointment_public_id') or '').strip()
    if raw_appointment_id:
        try:
            appointment_uuid = uuid.UUID(raw_appointment_id)
        except ValueError:
            return _error('invalid_appointment', 'Ungültige Terminreferenz.')
        appointment = Appointment.objects.filter(public_id=appointment_uuid, customer=customer).first()

    stored_name = ''
    original_name = ''
    mime_type = ''
    file_size = 0
    uploaded = request.FILES.get('file')
    created_path = None
    try:
        if uploaded:
            original_name = Path(uploaded.name or 'datei').name[:255]
            extension = Path(original_name).suffix.lower()
            if extension not in settings.PATIENT_FILE_ALLOWED_EXTENSIONS:
                return _error('file_type', 'Dieser Dateityp ist nicht erlaubt.')
            if uploaded.size <= 0:
                return _error('file_empty', 'Die Datei ist leer.')
            if uploaded.size > settings.PATIENT_FILE_MAX_BYTES:
                return _error('file_size', 'Die Datei ist zu groß.')
            stored_name = f'{customer.pk}/{uuid.uuid4().hex}{extension}'
            created_path = _patient_path(stored_name)
            created_path.parent.mkdir(parents=True, exist_ok=True)
            with created_path.open('wb') as handle:
                for chunk in uploaded.chunks():
                    handle.write(chunk)
            file_size = uploaded.size
            mime_type = (uploaded.content_type or mimetypes.guess_type(original_name)[0] or 'application/octet-stream')[:120]
        elif data.get('file_base64'):
            try:
                content = base64.b64decode(str(data.get('file_base64')), validate=True)
            except (binascii.Error, ValueError):
                return _error('invalid_file', 'Datei konnte nicht dekodiert werden.')
            stored_name, original_name, mime_type, file_size = _store_bytes(
                customer,
                str(data.get('original_name') or 'formular.pdf'),
                content,
                str(data.get('mime_type') or ''),
            )
            created_path = _patient_path(stored_name)
    except ValueError as exc:
        code = str(exc)
        messages = {
            'file_type': 'Dieser Dateityp ist nicht erlaubt.',
            'file_empty': 'Die Datei ist leer.',
            'file_size': 'Die Datei ist zu groß.',
        }
        return _error(code, messages.get(code, 'Datei konnte nicht gespeichert werden.'))

    if not title:
        title = Path(original_name).stem[:180] if original_name else 'Automatischer Akteneintrag'
    if not note and not stored_name:
        return _error('empty_record', 'Akteneintrag enthält weder Dokument noch Inhalt.')

    try:
        record = PatientRecord.objects.create(
            customer=customer,
            appointment=appointment,
            kind=kind,
            title=title,
            note=note,
            stored_name=stored_name,
            original_name=original_name,
            mime_type=mime_type,
            file_size=file_size,
            source=source,
            external_id=external_id,
            captured_at=_parse_captured_at(data.get('captured_at')),
            metadata=metadata,
            uploaded_by=None,
        )
    except Exception:
        if created_path and created_path.exists():
            try:
                created_path.unlink()
            except OSError:
                pass
        if external_id:
            existing = PatientRecord.objects.filter(source=source, external_id=external_id).first()
            if existing:
                return JsonResponse({
                    'ok': True,
                    'created': False,
                    'record_id': str(existing.public_id),
                    'customer_id': existing.customer_id,
                })
        raise

    return JsonResponse({
        'ok': True,
        'created': True,
        'record_id': str(record.public_id),
        'customer_id': customer.pk,
    }, status=201)
