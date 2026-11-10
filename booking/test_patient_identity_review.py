"""Test reviewed, reversible patient linking without cross-account record leakage."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .customer_identity import resolve_patient_identity
from .models import (
    AdminAccessProfile, Appointment, Customer, PatientIdentityDecision,
    PatientRecord, Service, StaffMember,
)
from .patient_identity_review import (
    approved_patient_groups, approved_patient_representatives,
    pair_fingerprint, possible_duplicate_pairs,
)


TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=TEST_STORAGES)
class PatientIdentityReviewTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username='identity-review-admin', password='x', is_staff=True,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        self.first = Customer.objects.create(
            first_name='Anna', last_name='Muster',
            email='anna.original@example.test', phone='+49 172 7779721',
        )
        self.second = Customer.objects.create(
            first_name='Anna', last_name='Muster',
            email='anna.new@example.test', phone='01727779721',
        )
        self.path = '/verwaltung/app/identity-review/'

    def payload(self, *, action='approve', first=None, second=None,
                confirmed=True, fingerprint=None):
        left = first or self.first
        right = second or self.second
        data = {
            'action': action,
            'left_id': str(left.pk),
            'right_id': str(right.pk),
            'primary_id': str(left.pk),
            'fingerprint': fingerprint or pair_fingerprint(left, right),
        }
        if confirmed:
            data['confirmed_same_patient'] = 'on'
        return data

    def test_matching_phone_and_name_different_email_produces_review_candidate(self):
        pairs = possible_duplicate_pairs()
        self.assertEqual(len(pairs), 1)
        self.assertIn('andere E-Mail', pairs[0]['reason'])
        self.assertEqual(PatientIdentityDecision.objects.count(), 0)

    def test_same_phone_but_different_full_name_is_not_suggested(self):
        self.second.last_name = 'Andere'
        self.second.save(update_fields=['last_name'])
        self.assertEqual(possible_duplicate_pairs(), [])

    def test_same_email_and_name_with_changed_phone_is_suggested(self):
        self.second.email = self.first.email
        self.second.phone = '+49 172 5555555'
        self.second.save(update_fields=['email', 'phone'])
        pairs = possible_duplicate_pairs()
        self.assertEqual(len(pairs), 1)
        self.assertIn('andere Telefonnummer', pairs[0]['reason'])

    def test_only_authenticated_confirmed_admin_can_review(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.path).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.path).status_code, 403)
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        self.assertEqual(self.client.get(self.path).status_code, 200)

        AdminAccessProfile.objects.create(user=self.admin, view_only=True)
        self.assertEqual(self.client.get(self.path).status_code, 403)
        self.assertEqual(self.client.post(self.path, self.payload()).status_code, 403)

    def test_missing_checkbox_does_not_link_records(self):
        response = self.client.post(self.path, self.payload(confirmed=False))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PatientIdentityDecision.objects.count(), 0)

    def test_outdated_browser_snapshot_is_rejected(self):
        response = self.client.post(self.path, self.payload(fingerprint='stale'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PatientIdentityDecision.objects.count(), 0)

    def test_unrelated_pair_cannot_be_approved_manually_without_evidence(self):
        third = Customer.objects.create(
            first_name='Someone', last_name='Else',
            email='other@example.test', phone='+4917622233344',
        )
        response = self.client.post(self.path, self.payload(second=third))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PatientIdentityDecision.objects.count(), 0)

    def test_admin_approval_is_audited_and_non_destructive(self):
        service = Service.objects.create(name='Beratung', slug='identity-review-test', duration_minutes=30)
        staff = StaffMember.objects.create(display_name='Dr. Test')
        staff.services.add(service)
        slot = timezone.now() + timedelta(days=3)
        appointment = Appointment.objects.create(
            customer=self.second, service=service, staff=staff,
            starts_at=slot, ends_at=slot + timedelta(minutes=30),
        )
        record = PatientRecord.objects.create(
            customer=self.second, appointment=appointment,
            kind='note', title='Vertraulicher Eintrag',
        )
        self.assertEqual([len(group) for group in approved_patient_groups([self.first, self.second])], [1, 1])

        response = self.client.post(self.path, self.payload())
        self.assertEqual(response.status_code, 302, response.content)
        event = PatientIdentityDecision.objects.get()
        self.assertEqual(event.action, 'approve')
        self.assertEqual(event.reviewed_by_id, self.admin.pk)
        self.assertEqual(event.primary_customer_id, self.first.pk)
        self.assertEqual(event.snapshot['right']['id'], self.second.pk)
        self.assertEqual(Customer.objects.count(), 2)
        self.assertEqual([len(group) for group in approved_patient_groups([self.first, self.second])], [2])
        grouped = approved_patient_representatives([self.first, self.second])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(set(grouped[0].display_group_ids), {self.first.pk, self.second.pk})

        appointment.refresh_from_db()
        record.refresh_from_db()
        self.assertEqual(appointment.customer_id, self.second.pk)
        self.assertEqual(record.customer_id, self.second.pk)
        # Clinical ingestion remains strict; review never changes its resolver.
        resolved, conflict = resolve_patient_identity(
            email=self.first.email, phone=self.first.phone,
            first_name=self.first.first_name, last_name=self.first.last_name,
        )
        self.assertIsNone(resolved)
        self.assertEqual(conflict, 'email_phone_conflict')

        # Both medical histories are visible to staff only AFTER approval.
        page = self.client.get(f'/verwaltung/app/patients/?customer={self.first.pk}&tab=records')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Vertraulicher Eintrag')

    def test_before_approval_patient_records_remain_separate(self):
        PatientRecord.objects.create(
            customer=self.second, kind='note', title='Eintrag nur in Profil zwei',
        )
        page = self.client.get(f'/verwaltung/app/patients/?customer={self.first.pk}&tab=records')
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Eintrag nur in Profil zwei')

    def test_rejection_is_logged_and_suppresses_candidate(self):
        response = self.client.post(self.path, self.payload(action='reject', confirmed=False))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(PatientIdentityDecision.objects.get().action, 'reject')
        self.assertEqual(possible_duplicate_pairs(), [])
        self.assertEqual(len(approved_patient_groups([self.first, self.second])), 2)

    def test_revocation_restores_separate_timelines_and_retains_audit_history(self):
        self.client.post(self.path, self.payload())
        self.assertEqual(len(approved_patient_groups([self.first, self.second])), 1)
        response = self.client.post(self.path, self.payload(action='revoke', confirmed=False))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(approved_patient_groups([self.first, self.second])), 2)
        self.assertEqual(
            list(PatientIdentityDecision.objects.order_by('pk').values_list('action', flat=True)),
            ['approve', 'revoke'],
        )
        self.assertEqual(len(possible_duplicate_pairs()), 1)

    def test_two_reviewers_cannot_submit_the_same_active_decision(self):
        first = self.client.post(self.path, self.payload())
        second = self.client.post(self.path, self.payload())
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(PatientIdentityDecision.objects.count(), 1)

    def test_csrf_protection_is_enforced_for_approval(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.admin)
        session = strict.session
        session['aplus_app_admin'] = True
        session.save()
        response = strict.post(self.path, self.payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(PatientIdentityDecision.objects.count(), 0)
