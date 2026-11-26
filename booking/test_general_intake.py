import base64
import io
import json
import shutil
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from datetime import date

from PIL import Image
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .intake_identity import locate_unique_intake_patient, match_score
from .models import Customer, OfficeIntakeAssignmentLock, OfficeIntakeForm, PatientRecord


FILES=tempfile.mkdtemp(prefix='book-office-forms-')


@override_settings(STORAGES={'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
                   PATIENT_SYNC_TOKEN='synthetic-test-token',
                   PATIENT_FILES_ROOT=FILES,
                   PATIENT_FILE_MAX_BYTES=10 * 1024 * 1024,
                   PATIENT_FILE_ALLOWED_EXTENSIONS={'.pdf','.jpg','.png'})
class GeneralIntakeTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(FILES,ignore_errors=True)

    def setUp(self):
        self.url='/api/internal/patient-intake/ingest/'
        self.identity=dict(first_name='Anna',last_name='Muster',email='anna@example.test',
            phone='+49 171 5551234',date_of_birth='1990-03-02',
            street='Teststraße 3',postal_code='60313',city='Frankfurt')
        picture=io.BytesIO()
        Image.new('RGB',(250,70),'white').save(picture,format='PNG')
        self.signature='data:image/png;base64,'+base64.b64encode(picture.getvalue()).decode()
        self.source_id=str(uuid.uuid4())
        self.data=dict(source_id=self.source_id,identity=self.identity,
                       answers={'allergies':'Nein','interests':['Laser','Hyaluron']},
                       consent_accepted=True,signature=self.signature)

    def submit(self, data=None, token='synthetic-test-token'):
        return self.client.post(self.url,data=json.dumps(data or self.data),
            content_type='application/json',HTTP_X_AESTHETIC_PATIENT_SYNC=token)

    def test_requires_service_authorization_and_signature(self):
        self.assertEqual(self.client.post(self.url,data=json.dumps(self.data),
            content_type='application/json').status_code,401)
        damaged={**self.data,'signature':''}
        self.assertEqual(self.submit(damaged).status_code,400)
        self.assertFalse(OfficeIntakeForm.objects.exists())

    def test_three_of_five_unique_matches_existing_without_changing_contact(self):
        patient=Customer.objects.create(first_name='Anna',last_name='Muster',
            email='older@example.test',phone='+49 172 0009999',date_of_birth=date(1990,3,2))
        self.assertEqual(match_score(self.identity,patient),3)
        response=self.submit()
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['status'],'linked')
        self.assertEqual(Customer.objects.count(),1)
        patient.refresh_from_db()
        self.assertEqual(patient.email,'older@example.test')
        form=OfficeIntakeForm.objects.get(source_id=self.source_id)
        self.assertEqual(form.customer_id,patient.pk)
        self.assertEqual(form.record.source,'office_intake')
        self.assertEqual(form.record.kind,'form')
        self.assertFalse(form.record.metadata['shared_with_customer'])
        self.assertTrue(form.record.has_file)
        self.assertEqual(self.submit().status_code,200)
        self.assertEqual(PatientRecord.objects.filter(source='office_intake').count(),1)

    def test_two_three_of_five_matches_go_to_review_without_attaching_records(self):
        for i in range(2):
            Customer.objects.create(first_name='Anna',last_name='Muster',
                email=f'old{i}@example.test',phone=f'+49 170 000000{i}',date_of_birth=date(1990,3,2))
        response=self.submit()
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(response.json()['status'],'review')
        self.assertFalse(PatientRecord.objects.filter(source='office_intake').exists())
        self.assertEqual(Customer.objects.count(),2)
        form=OfficeIntakeForm.objects.get(source_id=self.source_id)
        self.assertIsNone(form.customer_id)

    def test_new_patient_created_with_private_form_pdf(self):
        response=self.submit()
        self.assertEqual(response.status_code,201,response.content)
        form=OfficeIntakeForm.objects.get(source_id=self.source_id)
        self.assertEqual(form.status,'linked')
        self.assertEqual(form.customer.date_of_birth,date(1990,3,2))
        self.assertEqual(form.record.mime_type,'application/pdf')

    def test_book_admin_forms_filters_and_patient_tab(self):
        self.submit()
        User=get_user_model()
        staff=User.objects.create_user(username='clinicadmin',password='supersecret',
            is_staff=True,is_superuser=True)
        self.client.force_login(staff)
        session=self.client.session
        session['aplus_app_admin']=True
        session.save()
        inbox=self.client.get('/verwaltung/app/forms/?status=linked&q=Anna')
        self.assertEqual(inbox.status_code,200)
        self.assertContains(inbox,'Digitale Aufnahmebögen')
        self.assertContains(inbox,'Anna Muster')
        patient=Customer.objects.get()
        file=self.client.get(f'/verwaltung/app/patients/?customer={patient.pk}&tab=forms')
        self.assertEqual(file.status_code,200)
        self.assertContains(file,'Antworten &amp; Unterschrift')

    def test_invalid_fields_do_not_count_as_matches(self):
        invalid = {**self.identity, 'date_of_birth': '1990-02-31',
                   'email': 'invalid@', 'phone': 'not +491711234567'}
        self.assertEqual(match_score(invalid, invalid), 2)
        self.assertEqual(self.submit({**self.data, 'identity': invalid}).status_code, 400)
        self.assertFalse(Customer.objects.exists())

    def test_conflicting_known_birth_date_goes_to_manual_review(self):
        patient = Customer.objects.create(
            first_name=self.identity['first_name'], last_name=self.identity['last_name'],
            email=self.identity['email'], phone=self.identity['phone'], date_of_birth=date(1991, 3, 2),
        )
        self.assertEqual(match_score(self.identity, patient), 4)
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['status'], 'review')
        self.assertFalse(PatientRecord.objects.exists())
        staff = get_user_model().objects.create_user(username='intake-review-admin', is_staff=True)
        self.client.force_login(staff)
        detail = self.client.get('/verwaltung/app/forms/', {'form': OfficeIntakeForm.objects.get().pk})
        self.assertContains(detail, 'data-filter-patient-select="intakePatient"')
        self.assertContains(detail, patient.email)

    def test_changed_payload_cannot_reuse_existing_source_id(self):
        self.assertEqual(self.submit().status_code, 201)
        altered = {**self.data, 'answers': {'allergies': 'Ja'}}
        response = self.submit(altered)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'source_id_payload_mismatch')
        form = OfficeIntakeForm.objects.get(source_id=self.source_id)
        self.assertEqual(form.payload['answers'], self.data['answers'])
        self.assertEqual(PatientRecord.objects.count(), 1)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row-lock semantics')
class ConcurrentIntakeTests(TransactionTestCase):
    def test_concurrent_forms_with_same_identity_create_one_patient(self):
        OfficeIntakeAssignmentLock.objects.get_or_create(pk=1)
        picture = io.BytesIO()
        Image.new('RGB', (20, 20), 'white').save(picture, format='PNG')
        data = {
            'identity': {'first_name': 'Concurrent', 'last_name': 'Fixture',
                         'email': 'parallel@example.invalid', 'phone': '+491711234567',
                         'date_of_birth': '1995-01-01'},
            'answers': {'allergies': 'Nein'},
            'signature': 'data:image/png;base64,' + base64.b64encode(picture.getvalue()).decode(),
            'consent_accepted': True,
        }
        start = Barrier(2)

        def submit():
            close_old_connections()
            try:
                start.wait(timeout=10)
                return Client().post(
                    '/api/internal/patient-intake/ingest/',
                    json.dumps({**data, 'source_id': str(uuid.uuid4())}),
                    content_type='application/json',
                    HTTP_X_AESTHETIC_PATIENT_SYNC='synthetic-test-token',
                ).status_code
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as root, override_settings(
            PATIENT_SYNC_TOKEN='synthetic-test-token', PATIENT_FILES_ROOT=root,
        ), ThreadPoolExecutor(max_workers=2) as pool:
            responses = [pool.submit(submit) for _ in range(2)]
            self.assertEqual([r.result(timeout=20) for r in responses], [201, 201])
        self.assertEqual(Customer.objects.filter(email='parallel@example.invalid').count(), 1)
        self.assertEqual(OfficeIntakeForm.objects.filter(status='linked').count(), 2)
        self.assertEqual(PatientRecord.objects.filter(source='office_intake').count(), 2)
