import base64
import io
import json
import shutil
import tempfile
import uuid
from datetime import date

from PIL import Image
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .intake_identity import locate_unique_intake_patient, match_score
from .models import Customer, OfficeIntakeForm, PatientRecord


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
