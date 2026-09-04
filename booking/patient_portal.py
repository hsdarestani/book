import json
import logging
import mimetypes
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from .internal_api import _patient_path
from .models import Appointment, Customer, PatientRecord

logger = logging.getLogger(__name__)
APP_DOCUMENT_NOTIFICATION_URL = "https://esthetic.smarbiz.sbs/api/internal/patient-document/shared/"


def _notify_customer(record):
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    payload = json.dumps({
        "email": record.customer.email,
        "record_id": str(record.public_id),
        "title": record.title,
        "kind": record.kind,
        "shared": metadata.get("shared_with_customer") is True,
    }).encode("utf-8")
    request = Request(
        APP_DOCUMENT_NOTIFICATION_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "A+Esthetic-Book-PatientPortal/1.0",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        logger.warning("Patient portal notification callback failed", exc_info=True)
        return False


def _delete_created_file(stored_name):
    if not stored_name:
        return
    try:
        path = _patient_path(stored_name)
        if path.exists() and path.is_file():
            path.unlink()
    except (OSError, ValueError, Http404):
        pass


@staff_member_required(login_url="/verwaltung/login/")
@require_POST
def staff_add_record(request, customer_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    kind = str(request.POST.get("kind") or "document").strip()
    allowed_kinds = {value for value, _ in PatientRecord.KIND}
    if kind not in allowed_kinds:
        return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=type-error#akte")

    appointment = None
    appointment_id = str(request.POST.get("appointment_id") or "").strip()
    if appointment_id:
        appointment = Appointment.objects.filter(pk=appointment_id, customer=customer).first()

    title = str(request.POST.get("title") or "").strip()[:180]
    note = str(request.POST.get("note") or "").strip()[:6000]
    shared = request.POST.get("shared_with_customer") == "on"
    uploaded = request.FILES.get("file")
    stored_name = ""
    original_name = ""
    mime_type = ""
    file_size = 0

    try:
        if uploaded:
            original_name = Path(uploaded.name or "datei").name[:255]
            extension = Path(original_name).suffix.lower()
            if extension not in settings.PATIENT_FILE_ALLOWED_EXTENSIONS:
                return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=file-type#akte")
            if uploaded.size <= 0:
                return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=file-empty#akte")
            if uploaded.size > settings.PATIENT_FILE_MAX_BYTES:
                return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=file-size#akte")
            stored_name = f"{customer.pk}/{uuid.uuid4().hex}{extension}"
            destination = _patient_path(stored_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                for chunk in uploaded.chunks():
                    handle.write(chunk)
            file_size = uploaded.size
            mime_type = (uploaded.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream")[:120]
            if not title:
                title = Path(original_name).stem[:180] or "Datei"

        if not uploaded and not note:
            return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=empty#akte")
        if not title:
            title = "Notiz"
        if not uploaded and kind == "document":
            kind = "note"

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
            source="book_staff",
            metadata={
                "shared_with_customer": shared,
                "origin": "clinic",
                "shared_by_user_id": request.user.pk if shared else None,
            },
            uploaded_by=request.user,
        )
    except Exception:
        _delete_created_file(stored_name)
        raise

    if shared:
        _notify_customer(record)
    notice = "added-shared" if shared else "added"
    return redirect(f"/verwaltung/patienten/{customer.pk}/?notice={notice}#akte")


@staff_member_required(login_url="/verwaltung/login/")
@require_POST
def staff_toggle_share(request, customer_id, record_id):
    customer = get_object_or_404(Customer, pk=customer_id)
    record = get_object_or_404(PatientRecord, public_id=record_id, customer=customer)
    metadata = record.metadata.copy() if isinstance(record.metadata, dict) else {}
    current = metadata.get("shared_with_customer") is True or record.source in {"a_esthetic_app", "a_esthetic_app_customer"}

    # Customer-originated and consent records belong to the shared patient timeline.
    # Clinic staff may hide clinic-originated documents, but never silently revoke
    # the patient's access to a document they uploaded themselves.
    if record.source == "a_esthetic_app_customer":
        return redirect(f"/verwaltung/patienten/{customer.pk}/?notice=customer-owned#akte")

    target = not current
    metadata["shared_with_customer"] = target
    if target:
        metadata.pop("customer_archived_at", None)
        metadata["shared_by_user_id"] = request.user.pk
    else:
        metadata["unshared_by_user_id"] = request.user.pk
    record.metadata = metadata
    record.save(update_fields=["metadata"])
    if target:
        _notify_customer(record)
    return redirect(f"/verwaltung/patienten/{customer.pk}/?notice={'shared' if target else 'unshared'}#akte")
