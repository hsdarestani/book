"""Unified, private, multi-file patient record storage for all clinic surfaces."""
import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.db import transaction

from .internal_api import _patient_path
from .models import PatientRecord


class PatientUploadError(ValueError):
    pass


def save_patient_upload(*, user, customer, files, kind="document", title="", note="",
                        appointment=None, shared=False, source="book_staff"):
    """Create one record per attachment, all under the existing customer's id.

    Validate *all* inputs before writing; clean up created files when any
    storage/DB operation fails. A note-only submission produces one record.
    """
    files = list(files or [])
    if len(files) > 12:
        raise PatientUploadError("max_files")
    if not files and not str(note or "").strip():
        raise PatientUploadError("empty")
    if kind not in {key for key, _ in PatientRecord.KIND}:
        raise PatientUploadError("type_error")
    prepared = []
    for uploaded in files:
        filename = Path(uploaded.name or "datei").name[:255]
        ext = Path(filename).suffix.lower()
        if ext not in settings.PATIENT_FILE_ALLOWED_EXTENSIONS:
            raise PatientUploadError("file_type")
        if not (0 < uploaded.size <= settings.PATIENT_FILE_MAX_BYTES):
            raise PatientUploadError("file_size")
        mime = (uploaded.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream")[:120]
        prepared.append((uploaded, filename, ext, mime))
    created_files = []
    records = []
    try:
        with transaction.atomic():
            entries = prepared if prepared else [(None, "", "", "")]
            for index, (uploaded, filename, ext, mime) in enumerate(entries):
                stored = ""
                if uploaded:
                    stored = f"{customer.pk}/{uuid.uuid4().hex}{ext}"
                    target = _patient_path(stored)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("wb") as out:
                        for chunk in uploaded.chunks():
                            out.write(chunk)
                    created_files.append(target)
                record = PatientRecord.objects.create(
                    customer=customer, appointment=appointment,
                    kind=("photo" if mime.startswith("image/") else kind) if uploaded else "note",
                    title=(title[:180] if title else Path(filename).stem[:180] if filename else "Notiz"),
                    note=str(note or "").strip()[:6000] if index == 0 else "",
                    stored_name=stored, original_name=filename, mime_type=mime,
                    file_size=uploaded.size if uploaded else 0,
                    source=source,
                    metadata={"shared_with_customer": bool(shared), "origin": "clinic"},
                    uploaded_by=user,
                )
                records.append(record)
    except Exception:
        for path in created_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return records
