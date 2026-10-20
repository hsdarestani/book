import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Customer, PatientRecord
from .patient_uploads import PatientUploadError, save_patient_upload


class ClinicPhotoUploadTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            PATIENT_FILES_ROOT=Path(self.temp_dir.name),
            PATIENT_FILE_MAX_BYTES=1024 * 1024,
            PATIENT_FILE_ALLOWED_EXTENSIONS={".jpg", ".png", ".pdf"},
        )
        self.settings_override.enable()
        self.user = get_user_model().objects.create_user(username="clinic-test")
        self.patient = Customer.objects.create(
            first_name="Anna", last_name="Muster",
            email="anna@example.com", phone="+49 151 5553333")

    def tearDown(self):
        self.settings_override.disable()
        self.temp_dir.cleanup()

    def test_multiple_photos_share_existing_patient_directory(self):
        files = [
            SimpleUploadedFile("vorher.jpg", b"abc", content_type="image/jpeg"),
            SimpleUploadedFile("nachher.png", b"xyz", content_type="image/png"),
        ]
        rows = save_patient_upload(user=self.user, customer=self.patient,
                                   files=files, kind="photo", source="book_staff")
        self.assertEqual(len(rows), 2)
        self.assertEqual(PatientRecord.objects.count(), 2)
        for row in rows:
            self.assertTrue(row.stored_name.startswith(f"{self.patient.pk}/"))
            self.assertTrue((Path(self.temp_dir.name) / row.stored_name).exists())
            self.assertEqual(row.customer_id, self.patient.pk)
            self.assertFalse(row.metadata["shared_with_customer"])

    def test_one_invalid_file_rejects_entire_batch(self):
        files = [
            SimpleUploadedFile("okay.jpg", b"abc", content_type="image/jpeg"),
            SimpleUploadedFile("unsafe.exe", b"xyz", content_type="application/x-msdownload"),
        ]
        with self.assertRaises(PatientUploadError):
            save_patient_upload(user=self.user, customer=self.patient,
                                files=files, kind="photo")
        self.assertEqual(PatientRecord.objects.count(), 0)
        self.assertFalse((Path(self.temp_dir.name) / str(self.patient.pk)).exists())
