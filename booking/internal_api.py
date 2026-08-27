import base64
import binascii
import hashlib
import ipaddress
import json
import mimetypes
import re
import secrets
import socket
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Appointment, Customer, PatientRecord


def _error(code, message, status=400):
    return JsonResponse({'ok': False, 'error': code, 'message': message}, status=status)


def _sync_token():
    expected = str(getattr(settings, 'PATIENT_SYNC_TOKEN', '') or '').strip()
    if expected:
        return expected
    token_file = Path(getattr(settings, 'PATIENT_SYNC_TOKEN_FILE', '/etc/aesthetic-patient-sync.token'))
    try:
        return token_file.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return ''


def _normalize_ip(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _client_ip(request):
    forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR') or '')
    if forwarded:
        for value in reversed(forwarded.split(',')):
            address = _normalize_ip(value)
            if address is not None:
                return address
    return _normalize_ip(request.META.get('REMOTE_ADDR'))


def _trusted_source_addresses():
    addresses = set()
    for host in getattr(settings, 'PATIENT_SYNC_ALLOWED_HOSTS', []):
        host = str(host or '').strip()
        if not host:
            continue
        literal = _normalize_ip(host)
        if literal is not None:
            addresses.add(literal)
            continue
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except socket.gaierror:
            continue
        for info in infos:
            address = _normalize_ip(info[4][0])
            if address is not None:
                addresses.add(address)
    return addresses


def _trusted_source(request):
    client = _client_ip(request)
    if client is None:
        return False
    return client in _trusted_source_addresses()


def _proof_authorized(request):
    proof = str(request.headers.get('X-Aesthetic-Patient-Proof') or '').strip()
    verify_url = str(getattr(settings, 'PATIENT_SYNC_PROOF_VERIFY_URL', '') or '').strip()
    if not proof or not verify_url:
        return False
    content_type = (request.content_type or '').split(';', 1)[0].strip().lower()
    if content_type != 'application/json':
        return False
    body = request.body or b''
    if len(body) > int(getattr(settings, 'PATIENT_SYNC_PROOF_MAX_BODY_BYTES', 512 * 1024)):
        return False
    digest = hashlib.sha256(body).hexdigest()
    verification_body = json.dumps(
        {'proof': proof, 'sha256': digest}, separators=(',', ':')
    ).encode('utf-8')
    verification_request = URLRequest(
        verify_url,
        data=verification_body,
        method='POST',
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'A+Esthetic-Booking-Patient-Proof/1.0',
        },
    )
    try:
        timeout = float(getattr(settings, 'PATIENT_SYNC_PROOF_TIMEOUT', 5))
        with urlopen(verification_request, timeout=timeout) as response:
            result = json.loads(response.read().decode('utf-8') or '{}')
            return 200 <= response.status < 300 and result.get('ok') is True
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return False


def _authorized(request):
    # 1) Shared secret, when explicitly configured on both trusted backends.
    expected = _sync_token()
    if expected:
        provided = str(request.headers.get('X-Aesthetic-Patient-Sync') or '').strip()
        if not provided:
            authorization = str(request.headers.get('Authorization') or '').strip()
            if authorization.lower().startswith('bearer '):
                provided = authorization[7:].strip()
        if provided and secrets.compare_digest(provided, expected):
            return True

    # 2) Short-lived proof signed by the Customer Club server's own Django secret.
    # The proof is bound to SHA-256(request body); booking validates it by HTTPS
    # callback to the trusted A+Esthetic domain, so no shared credential is needed.
    if _proof_authorized(request):
        return True

    # 3) DNS/source-address fallback for deployments where the upstream address is
    # directly resolvable. This remains fail-closed behind CDNs/NAT.
    return _trusted_source(request)


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
    if not _authorized(request):
        return _error('unauthorized', 'Nicht autorisiert.', 401)

    data = _payload(request)
    if data is None:
        return _error('invalid_json', 'Ungültige Nutzdaten.')
    if data.get('action') == 'health':
        return JsonResponse({'ok': True, 'integration': 'patient_records'})

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
