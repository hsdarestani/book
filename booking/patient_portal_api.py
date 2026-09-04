import json
import uuid

from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .internal_api import _authorized, _error, _find_customer, _patient_path
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
    if not _authorized(request):
        return _error("unauthorized", "Nicht autorisiert.", 401)
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer = _customer_from_payload(data)
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
def portal_file(request):
    if not _authorized(request):
        return _error("unauthorized", "Nicht autorisiert.", 401)
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer = _customer_from_payload(data)
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
    if not _authorized(request):
        return _error("unauthorized", "Nicht autorisiert.", 401)
    data = _payload(request)
    if data is None:
        return _error("invalid_json", "Ungültige Nutzdaten.")
    customer = _customer_from_payload(data)
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
