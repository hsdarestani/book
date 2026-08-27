# A+Esthetic Patientenakte – Backend-Integration

The booking service exposes one server-to-server endpoint for completed consent forms and other patient documents:

`POST /api/internal/patient-records/ingest/`

This endpoint is **not** for browsers or mobile apps. It requires the shared server token in `X-Aesthetic-Patient-Sync` and stores uploaded files in the private patient-file area, outside public media storage.

## Identity and idempotency

Send the patient's email address and, when available, phone/name. Existing patients are matched by email first and normalized phone second. `source + external_id` is unique, so retries do not duplicate a form.

Recommended values:

- Customer Club consent: `source=a_esthetic_app`, `external_id=consent:<id>:acceptance`
- Consent withdrawal: `source=a_esthetic_app`, `external_id=consent:<id>:withdrawal`
- Botoxbogen: `source=botoxbogen`, `external_id=<stable form submission id>`

## JSON snapshot

Use JSON when the completed form is represented by structured text/evidence. Required practical fields are patient identity plus `note` or a file.

```json
{
  "source": "botoxbogen",
  "external_id": "submission-12345",
  "kind": "form",
  "title": "Botoxbogen 27.08.2026",
  "note": "Completed consent snapshot ...",
  "email": "patient@example.com",
  "phone": "+49 ...",
  "first_name": "Anna",
  "last_name": "Muster",
  "captured_at": "2026-08-27T18:00:00+02:00",
  "metadata": {"version": "3.0", "signed": true}
}
```

## Completed PDF/photo upload

For an actual generated PDF or image, send `multipart/form-data` with the same scalar fields plus `file`. Allowed file types and size limits are controlled by the booking service. Files are never served from a public media URL; authenticated `/verwaltung/` views stream them.

A JSON sender may alternatively use `file_base64`, `original_name`, and `mime_type` for small documents. Multipart is preferred for larger forms.

## Current integration

`hsdarestani/a_esthetic` automatically sends every `ConsentRecord` acceptance and withdrawal to this endpoint. It also runs an idempotent retry every 15 minutes. The existing Botoxbogen/WordPress form can use the same endpoint as soon as its completion hook is wired to this contract.
