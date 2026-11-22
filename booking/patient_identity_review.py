"""Non-destructive identity review for the clinic's patient records.

Phone + full name with a different email is a *candidate*, never proof of
identity. Only a human-reviewed, auditable decision can link records for the
staff-facing patient timeline. Customer IDs and external sync links remain
unchanged; customer-app permissions are not expanded by a staff review.
"""
import hashlib
import json
import unicodedata
from collections import defaultdict
from itertools import combinations

from .customer_identity import normalize_email, normalize_name, normalize_phone
from .models import Customer, PatientIdentityDecision


def ordered_pair(left, right):
    ids = sorted((int(left), int(right)))
    if ids[0] == ids[1]:
        raise ValueError('Zwei unterschiedliche Patienten auswählen.')
    return tuple(ids)


def identity_fields(patient):
    """Five independent match fields; unknown and placeholder values never match."""
    def name(value):
        value = normalize_name(unicodedata.normalize('NFC', str(value or '')))
        return '' if value in ('patient', 'simplybook', 'unknown', '-') else value

    phone = normalize_phone(patient.phone)
    # The legacy normalizer truncates overlong numbers. Never use a truncated
    # value as identity evidence.
    raw_digits = ''.join(ch for ch in str(patient.phone or '') if ch.isascii() and ch.isdigit())
    if len(raw_digits.removeprefix('00')) > 15:
        phone = ''
    dob = getattr(patient, 'date_of_birth', None)
    return (
        name(patient.first_name),
        name(patient.last_name),
        phone,
        normalize_email(patient.email),
        dob.isoformat() if dob else '',
    )


FIELD_LABELS = ('Vorname', 'Nachname', 'Telefonnummer', 'E-Mail', 'Geburtsdatum')


def matched_fields(left, right):
    return tuple(label for label, a, b in zip(FIELD_LABELS, identity_fields(left), identity_fields(right))
                 if a and b and a == b)


def match_evidence(left, right):
    """Three of five exact populated matches suggest review, never identity proof."""
    matches = matched_fields(left, right)
    if len(matches) < 3:
        return ''
    reason = f'{len(matches)}/5: ' + ', '.join(matches)
    dob_a, dob_b = getattr(left, 'date_of_birth', None), getattr(right, 'date_of_birth', None)
    if dob_a and dob_b and dob_a != dob_b:
        reason += '; anderes Geburtsdatum'
    elif matches == ('Vorname', 'Nachname', 'Telefonnummer'):
        reason += '; andere E-Mail'
    elif matches == ('Vorname', 'Nachname', 'E-Mail'):
        reason += '; andere Telefonnummer'
    return reason


def pair_fingerprint(left, right):
    """Include all five fields in the stale-review guard."""
    parts = [(item.pk, identity_fields(item)) for item in sorted((left, right), key=lambda value: value.pk)]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode('utf-8')).hexdigest()


def latest_decisions():
    decisions = {}
    for item in PatientIdentityDecision.objects.order_by('pk'):
        decisions[(item.left_id, item.right_id)] = item
    return decisions


def possible_duplicate_pairs(customers=None, *, limit=300, include_reviewed=False):
    """Suggest matches in deterministic order, avoiding quadratic all-customer scans."""
    items = list(customers if customers is not None else Customer.objects.order_by('pk'))
    # Index every populated triple (at most ten per record). This catches
    # every 3-of-5 combination without scanning unrelated pairs.
    by_triple = defaultdict(list)
    for item in items:
        populated = [(index, value) for index, value in enumerate(identity_fields(item)) if value]
        for triple in combinations(populated, 3):
            by_triple[triple].append(item)

    pairs = {}
    for members in by_triple.values():
        for left, right in combinations(members, 2):
            pair = ordered_pair(left.pk, right.pk)
            if pair not in pairs:
                reason = match_evidence(left, right)
                if reason:
                    pairs[pair] = (left, right, reason)

    decisions = latest_decisions()
    results = []
    for pair, (left, right, reason) in sorted(pairs.items(), key=lambda pair: pair[0]):
        decision = decisions.get(pair)
        if not include_reviewed and decision and decision.action in ('approve', 'reject'):
            continue
        results.append({
            'left': left,
            'right': right,
            'reason': reason,
            'fingerprint': pair_fingerprint(left, right),
            'decision': decision,
        })
        if len(results) >= limit:
            break
    return results


def approved_patient_groups(customers):
    """Show only explicitly verified aliases as one administrative patient.

    Booking rows, clinical records, external identity IDs and customer-app
    permissions are untouched. Rejected and revoked pairs are not re-linked
    automatically. Never join through an ambiguous name or telephone alone.
    """
    items = list(customers)
    by_id = {item.pk: item for item in items}
    parent = {item.pk: item.pk for item in items}
    members = {item.pk: {item.pk} for item in items}
    decisions = latest_decisions()
    separated = {key for key, decision in decisions.items()
                 if decision.action in ('reject', 'revoke')}

    def root(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    def join(left, right):
        a, b = root(left), root(right)
        if a == b:
            return
        # Explicitly separated accounts must stay separated even through
        # transitive matches (A↔B↔C may contain an explicit A≠C).
        if any(ordered_pair(i, j) in separated
               for i in members[a] for j in members[b]):
            return
        keep, remove = (a, b) if a < b else (b, a)
        parent[remove] = keep
        members[keep].update(members.pop(remove))

    # Keep explicit approved reviews, unless a later reject/revoke superseded
    # them in the append-only decision log.
    for (left, right), decision in decisions.items():
        if decision.action == 'approve' and left in by_id and right in by_id:
            join(left, right)

    # Candidate matches never expand clinical timelines. Only a recorded
    # approval joins aliases, including exact full-name / phone matches.

    groups = defaultdict(list)
    for item in items:
        groups[root(item.pk)].append(item)
    return list(groups.values())


def patient_group_sources(group):
    """Explain which independent sources contribute to the staff-only view."""
    if len(group) < 2:
        return []
    decisions = latest_decisions()
    sources = []
    for item in sorted(group, key=lambda x: x.pk):
        sources.append({
            'customer': item,
            'email': item.email,
            'phone': item.phone,
            'first_name': item.first_name,
            'last_name': item.last_name,
            'mode': 'Gesondertes Kundenprofil',
        })
    return sources


def approved_patient_representatives(customers, query=''):
    groups = approved_patient_groups(customers)
    needle = str(query or '').strip().casefold()
    result = []
    decisions = list(latest_decisions().values())
    for group in groups:
        searchable = ' '.join(
            f'{item.first_name} {item.last_name} {item.email} {item.phone}'
            for item in group
        ).casefold()
        if needle and needle not in searchable:
            continue
        # The chosen primary profile is only a label preference; no source
        # record or clinical document ownership is ever rewritten.
        group_ids = {item.pk for item in group}
        approvals = [
            decision for decision in decisions
            if decision.action == 'approve'
            and decision.primary_customer_id in group_ids
            and decision.left_id in group_ids and decision.right_id in group_ids
        ]
        approvals.sort(key=lambda decision: decision.pk, reverse=True)
        preferred = approvals[0].primary_customer_id if approvals else None
        representative = next((item for item in group if item.pk == preferred),
                              min(group, key=lambda item: item.pk))
        representative.display_group_ids = [item.pk for item in group]
        representative.display_profile_count = len(group)
        representative.display_group_emails = [item.email for item in group if normalize_email(item.email)]
        representative.display_group_phones = [item.phone for item in group if normalize_phone(item.phone)]
        result.append(representative)
    result.sort(key=lambda item: (normalize_name(item.last_name), normalize_name(item.first_name), item.pk))
    return result
