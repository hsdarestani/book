import base64
import json
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from .models import Customer, PatientRecord


class PatientRecordSyncTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(
            PATIENT_FILES_ROOT=Path(self.tmp.name),
            PATIENT_SYNC_TOKEN='integration-secret',
            PATIENT_FILE_MAX_BYTES=1024 * 1024,
            PATIENT_FILE_ALLOWED_EXTENSIONS={'.pdf', '.jpg', '.txt'},
        )
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        self.tmp.cleanup()
        super().tearDown()

    def payload(self):
        return {
            'source': 'a_esthetic_app',
            'external_id': 'consent:17:acceptance',
            'kind': 'form',
            'title': 'Einwilligung · Botox',
            'note': 'Version 2.1\nEinwilligung wurde digital bestätigt.',
            'email': 'anna@example.com',
            'phone': '+49 151 2345678',
            'first_name': 'Anna',
            'last_name': 'Muster',
            'captured_at': '2026-08-27T18:00:00+02:00',
            'metadata': {'template_key': 'botox', 'version': '2.1'},
        }

    def post(self, payload=None, token='integration-secret'):
        headers = {'HTTP_X_AESTHETIC_PATIENT_SYNC': token} if token is not None else {}
        return self.client.post(
            '/api/internal/patient-records/ingest/',
            data=json.dumps(payload or self.payload()),
            content_type='application/json',
            **headers,
        )

    def test_ingest_requires_shared_server_token(self):
        response = self.post(token='wrong')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(PatientRecord.objects.count(), 0)

    def test_consent_snapshot_creates_patient_and_record(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.content)
        record = PatientRecord.objects.select_related('customer').get()
        self.assertEqual(record.source, 'a_esthetic_app')
        self.assertEqual(record.external_id, 'consent:17:acceptance')
        self.assertEqual(record.kind, 'form')
        self.assertEqual(record.customer.email, 'anna@example.com')
        self.assertEqual(record.metadata['template_key'], 'botox')
        self.assertIsNotNone(record.captured_at)

    def test_external_reference_is_idempotent(self):
        first = self.post()
        second = self.post()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()['created'])
        self.assertEqual(PatientRecord.objects.count(), 1)
        self.assertEqual(Customer.objects.count(), 1)

    def test_base64_document_is_stored_in_private_patient_area(self):
        payload = self.payload()
        payload.update({
            'external_id': 'botoxbogen:42',
            'source': 'botoxbogen',
            'title': 'Botoxbogen 27.08.2026',
            'file_base64': base64.b64encode(b'%PDF-1.4 private form').decode('ascii'),
            'original_name': 'botoxbogen.pdf',
            'mime_type': 'application/pdf',
        })
        response = self.post(payload)
        self.assertEqual(response.status_code, 201, response.content)
        record = PatientRecord.objects.get()
        self.assertTrue(record.has_file)
        path = Path(self.tmp.name) / record.stored_name
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), b'%PDF-1.4 private form')
