"""A+ Esthetic patient archive picker regression coverage."""
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import get_template
from django.test import TestCase, override_settings, SimpleTestCase

from .models import Customer, PatientRecord


class ArchivePickerTemplateTests(SimpleTestCase):
    def test_multiple_picker_preview_and_safe_scope(self):
        template = get_template("booking/app_management.html").template.source
        self.assertIn('class="app-patient-upload patient-upload-studio"', template)
        self.assertIn('name="file" multiple', template)
        self.assertIn('data-upload-list', template)
        self.assertIn('data-upload-error', template)
        self.assertIn('data-upload-submit', template)
        self.assertIn('patient-upload-studio-inline-v2', template)
        self.assertIn('.patient-upload-studio label.patient-upload-drop', template)
        self.assertIn('.patient-goae-details>summary', template)
        self.assertIn('patient-studio-share', template)
        self.assertIn('patient-upload-studio-v1.js', template)
        self.assertNotIn('admin-patient-upload-preview-v12.js', template)
        self.assertIn('name="shared_with_customer"', template)

    def test_camera_does_not_replace_already_selected_files(self):
        source = (Path(__file__).resolve().parent.parent / "static/booking/admin-native-camera-v11.js").read_text()
        self.assertIn("Array.from(input.files || [])", source)
        self.assertIn("transfer.items.add(existing)", source)
        self.assertIn("transfer.items.add(file)", source)


class MultipleArchiveFilesTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(
            PATIENT_FILES_ROOT=Path(self.temp.name),
            PATIENT_FILE_MAX_BYTES=25 * 1024 * 1024,
        )
        self.override.enable()
        self.user = get_user_model().objects.create_user(
            username="upload-staff", is_staff=True, password="safe-test-password")
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            first_name="Alex", last_name="Muster",
            email="alex-upload@example.invalid", phone="+491234560000")

    def tearDown(self):
        self.override.disable()
        self.temp.cleanup()

    def test_attachments_remain_distinct_and_associated_with_correct_patient(self):
        photos = [
            SimpleUploadedFile("vorher.jpg", b"photo1", content_type="image/jpeg"),
            SimpleUploadedFile("nachher.png", b"photo2", content_type="image/png"),
            SimpleUploadedFile("bericht.pdf", b"%PDF-1.4", content_type="application/pdf"),
        ]
        with mock.patch("booking.patient_portal._notify_customer", return_value=True) as notify:
            response = self.client.post(
                f"/verwaltung/patienten/{self.customer.pk}/shared/add/",
                data={"kind": "document", "title": "Behandlung",
                      "note": "Sicher gespeichert", "shared_with_customer": "on",
                      "file": photos,
                      "return_to": f"/verwaltung/app/patients/?customer={self.customer.pk}&tab=records"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("added-shared", response["Location"])
        rows = list(PatientRecord.objects.filter(customer=self.customer).order_by("id"))
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.original_name for row in rows], ["vorher.jpg", "nachher.png", "bericht.pdf"])
        self.assertEqual([row.kind for row in rows], ["photo", "photo", "document"])
        self.assertEqual(rows[0].note, "Sicher gespeichert")
        self.assertEqual([row.note for row in rows[1:]], ["", ""])
        self.assertTrue(all(row.metadata["shared_with_customer"] for row in rows))
        self.assertEqual(notify.call_count, 3)
        self.assertTrue(all((Path(self.temp.name) / row.stored_name).exists() for row in rows))

    def test_rejects_more_than_twelve_without_partial_write(self):
        uploads = [SimpleUploadedFile(f"photo-{i}.jpg", b"jpeg", content_type="image/jpeg") for i in range(13)]
        response = self.client.post(
            f"/verwaltung/patienten/{self.customer.pk}/shared/add/",
            data={"kind": "photo", "file": uploads,
                  "return_to": f"/verwaltung/app/patients/?customer={self.customer.pk}&tab=records"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("max_files", response["Location"])
        self.assertFalse(PatientRecord.objects.filter(customer=self.customer).exists())
