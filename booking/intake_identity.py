"""Compare valid identity fields for private Office intake assignment."""

import re
import unicodedata
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .clinical_time import clinic_localdate
from .customer_identity import normalize_email, normalize_name, normalize_phone
from .models import Customer


def identity_values(data):
    def get(field):
        return data.get(field) if isinstance(data, dict) else getattr(data, field, None)

    def name(field):
        value = get(field)
        return normalize_name(unicodedata.normalize("NFC", value)) if isinstance(value, str) else ""

    try:
        dob = date.fromisoformat(str(get("date_of_birth") or "").strip())
    except ValueError:
        dob = None
    if dob and not date(1900, 1, 1) <= dob <= clinic_localdate():
        dob = None

    email = normalize_email(get("email"))
    try:
        validate_email(email)
    except ValidationError:
        email = ""

    raw = get("phone")
    digits = re.sub(r"\D", "", raw) if isinstance(raw, str) and re.fullmatch(r"[0-9+(). \t-]+", raw) else ""
    if digits.startswith("00"):
        digits = digits[2:]
    digits_count = len(digits) + int(digits.startswith("0"))
    phone = normalize_phone(raw) if 8 <= digits_count <= 15 else ""

    return (name("first_name"), name("last_name"), phone, dob.isoformat() if dob else "", email)


def _score(left, right):
    return sum(bool(a and b and a == b) for a, b in zip(left, right))


def match_score(left, right):
    return _score(identity_values(left), identity_values(right))


def _patients():
    return Customer.objects.only("first_name", "last_name", "email", "phone", "date_of_birth")


def intake_review_candidates(data):
    incoming = identity_values(data)
    return [patient for patient in _patients().order_by("last_name", "first_name").iterator()
            if _score(incoming, identity_values(patient)) >= 3]


def locate_unique_intake_patient(data):
    """Return a verified link, an exceptional review reason, or a new patient."""
    incoming = identity_values(data)
    if sum(bool(value) for value in incoming) < 3:
        return None, "missing_identity"

    qualifying = []
    contacts = set()
    for patient in _patients().iterator():
        values = identity_values(patient)
        if _score(incoming, values) >= 3:
            qualifying.append((patient, values[3]))
        if any(incoming[i] and incoming[i] == values[i] for i in (2, 4)):
            contacts.add(patient.pk)

    if len(qualifying) > 1:
        return None, "multiple_three_of_five_matches"
    if qualifying:
        patient, birth_date = qualifying[0]
        if contacts - {patient.pk}:
            return None, "contact_collision"
        if birth_date and incoming[3] and birth_date != incoming[3]:
            return None, "birth_date_conflict"
        return patient, ""
    if contacts:
        return None, "insufficient_identity_evidence"
    return None, ""
