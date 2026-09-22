import re

from django.db import transaction

from .models import Appointment, Customer, PatientRecord


def normalize_email(value):
    value = str(value or "").strip().lower()
    if "@" not in value or value.endswith("@invalid.local"):
        return ""
    return value


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = "49" + digits[1:]
    return digits[-15:] if len(digits) >= 8 else ""


def normalize_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def find_customer(*, email="", phone="", first_name="", last_name=""):
    normalized_email = normalize_email(email)
    if normalized_email:
        match = Customer.objects.filter(email__iexact=normalized_email).order_by("pk").first()
        if match:
            return match
    normalized_phone = normalize_phone(phone)
    first = normalize_name(first_name)
    last = normalize_name(last_name)
    if normalized_phone and first and last:
        for candidate in Customer.objects.exclude(phone="").order_by("pk"):
            if (
                normalize_phone(candidate.phone) == normalized_phone
                and normalize_name(candidate.first_name) == first
                and normalize_name(candidate.last_name) == last
            ):
                return candidate
    return None


def merge_customer(keeper, duplicate):
    if keeper.pk == duplicate.pk:
        return keeper
    with transaction.atomic():
        Appointment.objects.filter(customer=duplicate).update(customer=keeper)
        PatientRecord.objects.filter(customer=duplicate).update(customer=keeper)
        changed = []
        if not normalize_email(keeper.email) and normalize_email(duplicate.email):
            keeper.email = duplicate.email
            changed.append("email")
        if not keeper.phone and duplicate.phone:
            keeper.phone = duplicate.phone
            changed.append("phone")
        if not keeper.salutation and duplicate.salutation:
            keeper.salutation = duplicate.salutation
            changed.append("salutation")
        if not keeper.first_name and duplicate.first_name:
            keeper.first_name = duplicate.first_name
            changed.append("first_name")
        if not keeper.last_name and duplicate.last_name:
            keeper.last_name = duplicate.last_name
            changed.append("last_name")
        if changed:
            keeper.save(update_fields=changed + ["updated_at"])
        duplicate.delete()
    return keeper
