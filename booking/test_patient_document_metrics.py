import json
import shutil
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from .models import Customer, PatientRecord


TEMP_PATIENT_ROOT = tempfile.mkdtemp(prefix="aesthetic-patient-metrics-")


@override_settings(
    PATIENT_SYNC_TOKEN="metrics-secret",
    PATIENT_FILES_ROOT=TEMP_PATIENT_ROOT,
)
class PatientDocumentMetricsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_PATIENT_ROOT, ignore_errors=True)

    def setUp(self):
        self.customer = Customer.objects.create(
            first_name="Max",
            last_name="Muster",
            email="metrics@example.com",
            phone="+49 170 8888888",
        )
        stored_name = f"{self.customer.pk}/metrics.pdf"
        path = Path(TEMP_PATIENT_ROOT) / stored_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 test")
        self.record = PatientRecord.objects.create(
            customer=self.customer,
            kind="document",
            title="Metrics Test",
            stored_name=stored_name,
            original_name="metrics.pdf",
            mime_type="application/pdf",
            file_size=13,
            source="a_esthetic_app_customer",
            metadata={"shared_with_customer": True},
        )

    def request_file(self, download):
        return self.client.post(
            "/api/internal/patient-records/portal/file/",
            data=json.dumps({
                "email": self.customer.email,
                "phone": self.customer.phone,
                "record_id": str(self.record.public_id),
                "download": download,
            }),
            content_type="application/json",
            HTTP_X_AESTHETIC_PATIENT_SYNC="metrics-secret",
        )

    def test_customer_open_and_download_counts_are_separate(self):
        self.assertEqual(self.request_file(False).status_code, 200)
        self.assertEqual(self.request_file(False).status_code, 200)
        self.assertEqual(self.request_file(True).status_code, 200)

        self.record.refresh_from_db()
        self.assertEqual(self.record.metadata.get("customer_open_count"), 2)
        self.assertEqual(self.record.metadata.get("customer_download_count"), 1)
        self.assertTrue(self.record.metadata.get("customer_last_open_at"))
        self.assertTrue(self.record.metadata.get("customer_last_download_at"))
