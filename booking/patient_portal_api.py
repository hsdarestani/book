import base64
import binascii
import json
import uuid

from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import mobile_api
from .internal_api import _authorized, _error, _find_customer, _parse_captured_at, _patient_path, _store_bytes
from .models import PatientRecord


CUSTOMER_VISIBLE_SOURCES = {"a_esthetic_app", "a_esthetic_app_customer"}


def _payload(request):
    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _customer_from_payload(data):
    email = str(data.get("email") or "").strip().lower()[:254]
    phone = str(data.get("phone") or "").strip()[:40]
    return _find_customer(email, phone)


def _customer_for_request(request, data, *, create=False):
    # Internal server-to-server access remains available for maintenance and
    # backwards compatibility. Customer traffic uses the same Bearer token
    # verification already proven by the mobile booking API.
    if _authorized(request):
        return _customer_from_payload(data), None

    member, error = mobile_api._member(request)
    if error:
        return None, error
    if create:
        return mobile_api._customer(member), None
    return _find_customer(member["email"], member["phone"]), None


def _metadata(record):
    return record.metadata if isinstance(record.metadata, dict) else {}


def _visible_to_customer(record):
    metadata = _metadata(record)
    if metadata.get("customer_archived_at"):
        return False
    if record.source in CUSTOMER_VISIBLE_SOURCES:
        return True
    return metadata.get("shared_with_customer") is True


def _record_payload(record):
    metadata = _metadata(record)
    source_label = "customer" if record.source == "a_esthetic_app_customer" else "clinic"
    appointment = None
    if record.appointment_id:
        appointment = {
            "id": str(record.appointment.public_id),
            "service": record.appointment.service.name,
            "starts_at": record.appointment.starts_at.isoformat(),
        }
    return {
        "id": str(record.public_id),
        "kind": record.kind,
        "kind_label": record.get_kind_display(),
        "title": record.title,
        "note": record.note,
        "has_file": record.has_file,
        "is_image": record.is_image,
        "original_name": record.original_name,
        "mime_type": record.mime_type,
        "file_size": record.file_size,
        "source": source_label,
        "customer_uploaded": record.source == "a_esthetic_app_customer",
        "appointment": appointment,
        "captured_at": (record.captured_at or record.created_at).isoformat(),
        "created_at": record.created_at.isoformat(),
        "shared_with_customer": _visible_to_customer(record),
        "document_type": str(metadata.get("document_type") or ""),
    }


@csrf_exempt
@require_POST
def portal_list(request):
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer, auth_error = _customer_for_request(request, data)
    if auth_error:
        return auth_error
    if not customer:
        return JsonResponse({"ok": True, "patient_found": False, "records": []})

    records = (
        PatientRecord.objects.filter(customer=customer)
        .select_related("appointment", "appointment__service")
        .order_by("-created_at", "-pk")[:250]
    )
    visible = [_record_payload(record) for record in records if _visible_to_customer(record)]
    return JsonResponse({
        "ok": True,
        "patient_found": True,
        "customer": {
            "id": customer.pk,
            "name": customer.full_name,
            "email": customer.email,
        },
        "records": visible,
    })


@csrf_exempt
@require_POST
def portal_upload(request):
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer, auth_error = _customer_for_request(request, data, create=True)
    if auth_error:
        return auth_error
    if not customer:
        return _error("patient_not_found", "Patient nicht gefunden.", 404)

    if data.get("health_data_consent") is not True:
        return _error("health_data_consent_required", "Einwilligung für den Dokument-Upload erforderlich.", 409)

    kind = str(data.get("kind") or "document").strip()
    if kind not in {value for value, _ in PatientRecord.KIND}:
        return _error("invalid_kind", "Ungültiger Akten-Typ.")
    title = str(data.get("title") or "").strip()[:180]
    note = str(data.get("note") or "").strip()[:6000]
    external_id = str(data.get("external_id") or f"customer-upload:{uuid.uuid4().hex}").strip()[:180]
    existing = PatientRecord.objects.filter(source="a_esthetic_app_customer", external_id=external_id).first()
    if existing:
        if existing.customer_id != customer.pk:
            return _error("record_conflict", "Dokumentreferenz ist bereits vergeben.", 409)
        return JsonResponse({"ok": True, "created": False, "record_id": str(existing.public_id), "customer_id": customer.pk})

    stored_name = ""
    original_name = ""
    mime_type = ""
    file_size = 0
    created_path = None
    if data.get("file_base64"):
        try:
            content = base64.b64decode(str(data.get("file_base64")), validate=True)
        except (binascii.Error, ValueError):
            return _error("invalid_file", "Datei konnte nicht dekodiert werden.")
        try:
            stored_name, original_name, mime_type, file_size = _store_bytes(
                customer,
                str(data.get("original_name") or "dokument.pdf"),
                content,
                str(data.get("mime_type") or ""),
            )
            created_path = _patient_path(stored_name)
        except ValueError as exc:
            code = str(exc)
            return _error(code, {
                "file_type": "Dieser Dateityp ist nicht erlaubt.",
                "file_empty": "Die Datei ist leer.",
                "file_size": "Die Datei ist zu groß.",
            }.get(code, "Datei konnte nicht gespeichert werden."), 413 if code == "file_size" else 400)

    if not title:
        title = (original_name.rsplit(".", 1)[0] if original_name else "Notiz")[:180]
    if not stored_name and not note:
        return _error("empty_record", "Akteneintrag enthält weder Dokument noch Inhalt.")

    metadata = {
        "document_type": "customer_upload",
        "customer_upload": True,
        "shared_with_customer": True,
        "health_data_consent": True,
    }
    try:
        record = PatientRecord.objects.create(
            customer=customer,
            kind=kind,
            title=title,
            note=note,
            stored_name=stored_name,
            original_name=original_name,
            mime_type=mime_type,
            file_size=file_size,
            source="a_esthetic_app_customer",
            external_id=external_id,
            captured_at=_parse_captured_at(data.get("captured_at")),
            metadata=metadata,
            uploaded_by=None,
        )
    except Exception:
        if created_path and created_path.exists():
            try:
                created_path.unlink()
            except OSError:
                pass
        raise

    return JsonResponse({"ok": True, "created": True, "record_id": str(record.public_id), "customer_id": customer.pk}, status=201)


@csrf_exempt
@require_POST
def portal_file(request):
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer, auth_error = _customer_for_request(request, data)
    if auth_error:
        return auth_error
    if not customer:
        return _error("patient_not_found", "Patient nicht gefunden.", 404)
    try:
        record_id = uuid.UUID(str(data.get("record_id") or ""))
    except ValueError:
        return _error("invalid_record", "Ungültige Dokumentreferenz.")
    record = PatientRecord.objects.filter(public_id=record_id, customer=customer).first()
    if not record or not _visible_to_customer(record):
        return _error("record_not_found", "Dokument nicht gefunden.", 404)
    if not record.stored_name:
        return _error("file_not_found", "Keine Datei vorhanden.", 404)
    path = _patient_path(record.stored_name)
    if not path.exists() or not path.is_file():
        return _error("file_not_found", "Datei nicht gefunden.", 404)
    response = FileResponse(
        path.open("rb"),
        content_type=record.mime_type or "application/octet-stream",
        as_attachment=bool(data.get("download")),
        filename=record.original_name or path.name,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Aesthetic-File-Name"] = (record.original_name or path.name).encode("ascii", "ignore").decode("ascii")[:180]
    return response


@csrf_exempt
@require_POST
def portal_archive(request):
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer, auth_error = _customer_for_request(request, data)
    if auth_error:
        return auth_error
    if not customer:
        return _error("patient_not_found", "Patient nicht gefunden.", 404)
    try:
        record_id = uuid.UUID(str(data.get("record_id") or ""))
    except ValueError:
        return _error("invalid_record", "Ungültige Dokumentreferenz.")
    record = PatientRecord.objects.filter(public_id=record_id, customer=customer).first()
    if not record or record.source != "a_esthetic_app_customer":
        return _error("record_not_found", "Eigenes Dokument nicht gefunden.", 404)
    metadata = _metadata(record).copy()
    metadata["customer_archived_at"] = timezone.now().isoformat()
    metadata["shared_with_customer"] = False
    record.metadata = metadata
    record.save(update_fields=["metadata"])
    return JsonResponse({"ok": True, "archived": True, "record_id": str(record.public_id)})
