"""Non-destructive identity review for the clinic's patient records.

Phone + full name with a different email is a *candidate*, never proof of
identity. Only a human-reviewed, auditable decision can link records for the
staff-facing patient timeline. Customer IDs and external sync links remain
unchanged; customer-app permissions are not expanded by a staff review.
"""
import hashlib
from collections import defaultdict

from .customer_identity import normalize_email, normalize_name, normalize_phone
from .models import Customer, PatientIdentityDecision


def ordered_pair(left, right):
    ids = sorted((int(left), int(right)))
    if ids[0] == ids[1]:
        raise ValueError('Zwei unterschiedliche Patienten auswählen.')
    return tuple(ids)


def match_evidence(left, right):
    """Return an explanation only for a high-confidence potential match."""
    name_a = (normalize_name(left.first_name), normalize_name(left.last_name))
    name_b = (normalize_name(right.first_name), normalize_name(right.last_name))
    full_name = all(name_a) and all(name_b) and name_a == name_b
    phone_a, phone_b = normalize_phone(left.phone), normalize_phone(right.phone)
    email_a, email_b = normalize_email(left.email), normalize_email(right.email)
    same_phone = bool(phone_a and phone_b and phone_a == phone_b)
    same_email = bool(email_a and email_b and email_a == email_b)
    # A shared phone or email without a matching full name is not enough to
    # recommend combining two medical files (households may share both).
    if full_name and same_phone and email_a != email_b:
        return 'Gleicher Vorname, Nachname und Telefonnummer; andere E-Mail'
    if full_name and same_email and phone_a != phone_b:
        return 'Gleicher Vorname, Nachname und E-Mail; andere Telefonnummer'
    if full_name and same_phone and same_email:
        return 'Gleicher vollständiger Name, E-Mail und Telefonnummer'
    return ''


def pair_fingerprint(left, right):
    """Guard against approving an old browser view after patient data change."""
    parts = []
    for item in sorted((left, right), key=lambda value: value.pk):
        parts.extend([str(item.pk), normalize_email(item.email),
                      normalize_phone(item.phone), normalize_name(item.first_name),
                      normalize_name(item.last_name)])
    return hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()


def latest_decisions():
    decisions = {}
    for item in PatientIdentityDecision.objects.order_by('pk'):
        decisions[(item.left_id, item.right_id)] = item
    return decisions


def possible_duplicate_pairs(customers=None, *, limit=300, include_reviewed=False):
    """Suggest matches in deterministic order, avoiding quadratic all-customer scans."""
    items = list(customers if customers is not None else Customer.objects.order_by('pk'))
    by_phone_name = defaultdict(list)
    by_email_name = defaultdict(list)
    for item in items:
        first, last = normalize_name(item.first_name), normalize_name(item.last_name)
        if not first or not last:
            continue
        phone, email = normalize_phone(item.phone), normalize_email(item.email)
        if phone:
            by_phone_name[(phone, first, last)].append(item)
        if email:
            by_email_name[(email, first, last)].append(item)

    pairs = {}
    for index in (by_phone_name, by_email_name):
        for members in index.values():
            if len(members) < 2:
                continue
            for position, left in enumerate(members):
                for right in members[position+1:]:
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
    """Only staff-approved links combine otherwise independent patient views."""
    items = list(customers)
    by_id = {item.pk: item for item in items}
    parent = {item.pk: item.pk for item in items}

    def root(pk):
        while parent[pk] != pk:
            parent[pk] = parent[parent[pk]]
            pk = parent[pk]
        return pk

    def join(left, right):
        a, b = root(left), root(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for (left, right), decision in latest_decisions().items():
        if decision.action == 'approve' and left in by_id and right in by_id:
            join(left, right)

    groups = defaultdict(list)
    for item in items:
        groups[root(item.pk)].append(item)
    return list(groups.values())


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
