import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Customer, PatientRecord


class SharedPatientPortalTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(
            PATIENT_FILES_ROOT=Path(self.temp.name),
            PATIENT_SYNC_ALLOWED_HOSTS=[],
        )
        self.override.enable()
        self.customer = Customer.objects.create(
            first_name="Paula",
            last_name="Patient",
            email="paula@example.de",
            phone="+49123456789",
        )
        self.staff = User.objects.create_user(
            username="staff",
            password="Password-123!",
            is_staff=True,
        )

    def tearDown(self):
        self.override.disable()
        self.temp.cleanup()

    def _post_json(self, path, payload):
        with mock.patch("booking.patient_portal_api._authorized", return_value=True):
            return self.client.post(path, data=json.dumps(payload), content_type="application/json")

    def test_list_contains_only_shared_and_app_origin_records(self):
        private = PatientRecord.objects.create(
            customer=self.customer,
            kind="note",
            title="Interne Notiz",
            note="Nur Team",
            source="book_staff",
            metadata={"shared_with_customer": False},
        )
        shared = PatientRecord.objects.create(
            customer=self.customer,
            kind="document",
            title="Geteiltes Dokument",
            note="Für Kunde",
            source="book_staff",
            metadata={"shared_with_customer": True},
        )
        customer_upload = PatientRecord.objects.create(
            customer=self.customer,
            kind="photo",
            title="Kundenfoto",
            note="Vom Kunden",
            source="a_esthetic_app_customer",
            metadata={"customer_upload": True, "shared_with_customer": True},
        )

        response = self._post_json(
            "/api/internal/patient-records/portal/list/",
            {"email": self.customer.email},
        )
        self.assertEqual(response.status_code, 200, response.content)
        titles = [item["title"] for item in response.json()["records"]]
        self.assertEqual(titles, ["Kundenfoto", "Geteiltes Dokument"])
        self.assertNotIn(private.title, titles)
        self.assertTrue(response.json()["patient_found"])
        self.assertEqual(str(shared.public_id), response.json()["records"][1]["id"])

    def test_customer_can_archive_only_own_upload_without_deleting_clinic_history(self):
        own = PatientRecord.objects.create(
            customer=self.customer,
            kind="document",
            title="Mein Upload",
            note="test",
            source="a_esthetic_app_customer",
            metadata={"shared_with_customer": True},
        )
        clinic = PatientRecord.objects.create(
            customer=self.customer,
            kind="document",
            title="Praxis",
            note="test",
            source="book_staff",
            metadata={"shared_with_customer": True},
        )

        denied = self._post_json(
            "/api/internal/patient-records/portal/archive/",
            {"email": self.customer.email, "record_id": str(clinic.public_id)},
        )
        self.assertEqual(denied.status_code, 404)

        archived = self._post_json(
            "/api/internal/patient-records/portal/archive/",
            {"email": self.customer.email, "record_id": str(own.public_id)},
        )
        self.assertEqual(archived.status_code, 200, archived.content)
        own.refresh_from_db()
        self.assertIn("customer_archived_at", own.metadata)
        self.assertTrue(PatientRecord.objects.filter(pk=own.pk).exists())

        listing = self._post_json(
            "/api/internal/patient-records/portal/list/",
            {"email": self.customer.email},
        )
        self.assertEqual([row["title"] for row in listing.json()["records"]], ["Praxis"])

    def test_staff_shared_upload_is_written_to_same_patient_record_and_visible(self):
        self.client.force_login(self.staff)
        upload = SimpleUploadedFile("befund.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        with mock.patch("booking.patient_portal._notify_customer", return_value=True):
            response = self.client.post(
                f"/verwaltung/patienten/{self.customer.pk}/shared/add/",
                data={
                    "kind": "document",
                    "title": "Befund",
                    "note": "Für die gemeinsame Akte",
                    "shared_with_customer": "on",
                    "file": upload,
                },
            )
        self.assertEqual(response.status_code, 302)
        record = PatientRecord.objects.get(title="Befund")
        self.assertEqual(record.source, "book_staff")
        self.assertTrue(record.metadata["shared_with_customer"])
        self.assertEqual(record.uploaded_by, self.staff)
        self.assertTrue((Path(self.temp.name) / record.stored_name).exists())

        listing = self._post_json(
            "/api/internal/patient-records/portal/list/",
            {"email": self.customer.email},
        )
        self.assertEqual(listing.json()["records"][0]["title"], "Befund")

    def test_private_file_is_not_downloadable_through_customer_gateway(self):
        stored = f"{self.customer.pk}/private.pdf"
        path = Path(self.temp.name) / stored
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private")
        record = PatientRecord.objects.create(
            customer=self.customer,
            kind="document",
            title="Intern",
            stored_name=stored,
            original_name="private.pdf",
            mime_type="application/pdf",
            file_size=7,
            source="book_staff",
            metadata={"shared_with_customer": False},
        )
        response = self._post_json(
            "/api/internal/patient-records/portal/file/",
            {"email": self.customer.email, "record_id": str(record.public_id)},
        )
        self.assertEqual(response.status_code, 404)
