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


def duplicate_customer_groups(customers=None):
    """Group exact duplicate identities without changing or deleting records."""
    items = list(customers if customers is not None else Customer.objects.order_by("pk"))
    parent = {item.pk: item.pk for item in items}

    def find(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    def union(left, right):
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    by_email = {}
    by_phone = {}
    for item in items:
        email = normalize_email(item.email)
        if email:
            if email in by_email:
                union(item.pk, by_email[email])
            else:
                by_email[email] = item.pk

        # Patient COUNT is intentionally more permissive than destructive
        # customer merging. A normalized phone number is treated as one real
        # patient for dashboard statistics even if names/e-mails differ
        # slightly between app, SimplyBook or legacy imports.
        phone = normalize_phone(item.phone)
        if phone:
            if phone in by_phone:
                union(item.pk, by_phone[phone])
            else:
                by_phone[phone] = item.pk

    groups = {}
    for item in items:
        groups.setdefault(find(item.pk), []).append(item)
    return list(groups.values())


def unique_customer_count(customers=None):
    return len(duplicate_customer_groups(customers))


def grouped_customers_for_display(customers=None, query=""):
    """Return one stable representative per duplicate identity group.

    This is presentation-only. It never mutates, merges or deletes Customer rows.
    A query matches any profile inside the group, so legacy aliases remain findable.
    """
    groups = duplicate_customer_groups(customers)
    needle = str(query or "").strip().casefold()
    rows = []
    for group in groups:
        if needle:
            searchable = " ".join(
                " ".join([
                    str(item.first_name or ""),
                    str(item.last_name or ""),
                    str(item.email or ""),
                    str(item.phone or ""),
                ])
                for item in group
            ).casefold()
            if needle not in searchable:
                continue

        # Stable representative: prefer the oldest row with the most useful contact data.
        representative = sorted(
            group,
            key=lambda item: (
                -(1 if normalize_phone(item.phone) else 0),
                -(1 if normalize_email(item.email) else 0),
                item.pk,
            ),
        )[0]
        representative.display_profile_count = len(group)
        representative.display_group_ids = [item.pk for item in group]
        representative.display_group_emails = [item.email for item in group if normalize_email(item.email)]
        representative.display_group_phones = [item.phone for item in group if normalize_phone(item.phone)]
        rows.append(representative)

    rows.sort(key=lambda item: (
        normalize_name(item.last_name),
        normalize_name(item.first_name),
        item.pk,
    ))
    return rows


def duplicate_customer_count(customers=None):
    return sum(max(0, len(group) - 1) for group in duplicate_customer_groups(customers))


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


def resolve_patient_identity(*, email="", phone="", first_name="", last_name=""):
    """Resolve one customer safely for medical record ingestion.

    Return (customer, reason), never join two different people by a shared
    telephone number, and never pick an arbitrary row out of legacy duplicates.
    Callers must not write a clinical record when reason is nonempty.
    """
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone)
    name_first, name_last = normalize_name(first_name), normalize_name(last_name)
    email_matches = list(Customer.objects.filter(email__iexact=normalized_email).order_by("pk")) if normalized_email else []
    if len(email_matches) > 1:
        return None, "duplicate_email"
    phone_matches = [
        candidate for candidate in Customer.objects.exclude(phone="").order_by("pk")
        if normalized_phone and normalize_phone(candidate.phone) == normalized_phone
    ]
    email_match = email_matches[0] if email_matches else None
    if email_match:
        other_phone_matches = [p for p in phone_matches if p.pk != email_match.pk]
        if other_phone_matches:
            return None, "email_phone_conflict"
        if name_first and name_last and (
            normalize_name(email_match.first_name) not in ("", "patient", name_first)
            or normalize_name(email_match.last_name) not in ("", name_last)
        ):
            return None, "name_conflict"
        return email_match, ""
    if phone_matches:
        same_name = [
            p for p in phone_matches
            if name_first and name_last
            and normalize_name(p.first_name) == name_first
            and normalize_name(p.last_name) == name_last
        ]
        if len(same_name) == 1 and len(phone_matches) == 1:
            return same_name[0], ""
        return None, "phone_identity_conflict"
    return None, ""
