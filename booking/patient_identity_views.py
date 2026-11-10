"""Privacy-preserving staff UI for reviewing potential duplicate patient profiles."""
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import Appointment, Customer, PatientIdentityDecision, PatientRecord
from .patient_identity_review import (
    latest_decisions, match_evidence, ordered_pair,
    pair_fingerprint, possible_duplicate_pairs,
)


def _authorized(request):
    """Only confirmed A+ clinic administrators, never clinicians/read-only staff."""
    try:
        profile = request.user.aesthetic_access
        if profile.view_only:
            return False
    except Exception:
        pass
    return bool(request.user.is_active and request.user.is_staff
                and request.session.get('aplus_app_admin') is True)


def _process_decision(request):
    post = request.POST
    try:
        pair = ordered_pair(int(post.get('left_id')), int(post.get('right_id')))
        chosen_id = int(post.get('primary_id'))
    except (ValueError, TypeError):
        raise ValueError('Bitte zwei gültige Patienten auswählen.')

    action = str(post.get('action') or '')
    if action not in {'approve', 'reject', 'revoke'}:
        raise ValueError('Unbekannte Entscheidung.')
    if chosen_id not in pair:
        raise ValueError('Die Hauptakte muss zu den zwei geprüften Profilen gehören.')

    with transaction.atomic():
        locked = list(Customer.objects.select_for_update().filter(pk__in=pair).order_by('pk'))
        if len(locked) != 2:
            raise ValueError('Eines der Patientenprofile wurde inzwischen entfernt.')
        left, right = locked
        previous = latest_decisions().get(pair)

        if action == 'revoke':
            if not previous or previous.action not in {'approve', 'reject'}:
                raise ValueError('Es gibt keine aktive Entscheidung zum Aufheben.')
        else:
            if previous and previous.action in {'approve', 'reject'}:
                raise ValueError('Diese Prüfung wurde bereits bearbeitet. Seite neu laden.')
            evidence = match_evidence(left, right)
            if not evidence:
                raise ValueError('Der automatische Datenabgleich passt nicht mehr. Bitte manuell prüfen.')
            if post.get('fingerprint') != pair_fingerprint(left, right):
                raise ValueError('Patientendaten wurden geändert. Bitte die Seite neu laden.')
            if action == 'approve' and post.get('confirmed_same_patient') != 'on':
                raise ValueError('Bitte bestätigen, dass die Identität geprüft wurde.')

        evidence = match_evidence(left, right)
        PatientIdentityDecision.objects.create(
            left=left,
            right=right,
            primary_customer_id=chosen_id,
            action=action,
            reviewed_by=request.user,
            reason=evidence or 'Manuelle Rücknahme einer früheren Entscheidung',
            snapshot={
                'left': {
                    'id': left.pk, 'name': left.full_name,
                    'email': left.email, 'phone': left.phone,
                },
                'right': {
                    'id': right.pk, 'name': right.full_name,
                    'email': right.email, 'phone': right.phone,
                },
                'previous_action': previous.action if previous else None,
            },
        )


@never_cache
@staff_member_required(login_url='/verwaltung/login/')
@require_http_methods(['GET', 'POST'])
def identity_review(request):
    if not _authorized(request):
        return HttpResponseForbidden('Nur bestätigte A+ Administratoren können Patientenzuordnungen prüfen.')

    if request.method == 'POST':
        try:
            _process_decision(request)
        except ValueError as exc:
            return _render_review(request, error=str(exc), status=409)
        return redirect('/verwaltung/app/identity-review/?notice=saved')

    return _render_review(request)


def _render_review(request, *, error='', status=200):
    rows = possible_duplicate_pairs(limit=150)
    relevant_ids = set()
    for item in rows:
        relevant_ids.update((item['left'].pk, item['right'].pk))
    appointment_counts = {
        row['customer_id']: row['total']
        for row in Appointment.objects.filter(customer_id__in=relevant_ids)
        .values('customer_id').annotate(total=Count('pk'))
    }
    record_counts = {
        row['customer_id']: row['total']
        for row in PatientRecord.objects.filter(customer_id__in=relevant_ids)
        .values('customer_id').annotate(total=Count('pk'))
    }
    for item in rows:
        for side in ('left', 'right'):
            customer = item[side]
            customer.review_appointments = appointment_counts.get(customer.pk, 0)
            customer.review_records = record_counts.get(customer.pk, 0)
    # Historical decisions are for administrator visibility; every event
    # remains in the database even if the same pair is later reversed.
    last = list(latest_decisions().values())
    last.sort(key=lambda item: item.pk, reverse=True)
    return render(request, 'booking/patient_identity_review.html', {
        'candidates': rows,
        'latest_reviews': last[:25],
        'error': error,
        'notice': request.GET.get('notice') == 'saved',
    }, status=status)
