import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from PIL import Image

from .models import AdminAccessProfile, Customer, PatientRecord, StaffMember


def sample_pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>']
    for page, content in ((3, 4), (5, 6)):
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Resources << /Font << /F1 7 0 R >> >> /Contents {content} 0 R >>'.encode())
        stream = f'BT /F1 20 Tf 30 350 Td (Preview page {(page - 1) // 2}) Tj ET'.encode()
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream')
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    data = b'%PDF-1.4\n'
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n'
    xref = len(data)
    data += f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode()
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    data += f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return data


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class RecordPreviewTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings_override = override_settings(PATIENT_FILES_ROOT=Path(self.temp.name))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_user('record-admin', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(first_name='Sophie', last_name='Muster', email='sophie@example.invalid')
        self.record = self.make_record('preview.pdf', sample_pdf(), 'application/pdf')
        self.base = f'/verwaltung/patienten/{self.customer.pk}/datei/{self.record.public_id}/'

    def make_record(self, name, data, mime):
        stored = f'{self.customer.pk}/{name}'
        path = Path(self.temp.name, stored)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        return PatientRecord.objects.create(customer=self.customer, title='Example record',
            original_name=name, stored_name=stored, mime_type=mime, file_size=len(data))

    def test_legacy_pdf_link_enters_same_tab_viewer_and_original_still_downloads(self):
        response = self.client.get(self.base)
        self.assertRedirects(response, self.base + 'ansicht/', fetch_redirect_response=False)
        for query in ('?raw=1', '?download=1'):
            response = self.client.get(self.base + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/pdf')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertIn('attachment', response['Content-Disposition'])

    def test_pdf_viewer_has_real_page_navigation_without_native_embed(self):
        response = self.client.get(self.base + 'ansicht/?page=2')
        self.assertContains(response, 'Seite 2 von 2')
        self.assertContains(response, 'vorschau/?page=2&amp;size=page')
        self.assertNotContains(response, '<iframe')
        self.assertNotContains(response, 'target="_blank"')
        self.assertIn('no-store', response['Cache-Control'])
        session = self.client.session
        session['aplus_app_admin'] = True
        session.save()
        response = self.client.get(self.base + 'ansicht/')
        self.assertNotContains(response, 'data-drawer')
        self.assertNotContains(response, 'admin-luxury-v2.js')

    def test_thumbnail_and_second_pdf_page_are_real_private_images(self):
        for query in ('', '?page=2&size=page'):
            response = self.client.get(self.base + 'vorschau/' + query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['X-Preview-State'], 'ready')
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertIn('private', response['Cache-Control'])
            image = Image.open(io.BytesIO(response.content))
            self.assertGreater(image.width, 300)
            self.assertLessEqual(image.height, 2200)
            self.assertLess(image.convert('L').getextrema()[0], 100)  # Text really rendered.

    def test_images_and_text_have_in_browser_previews(self):
        buffer = io.BytesIO()
        Image.new('RGB', (800, 600), 'navy').save(buffer, 'PNG')
        photo = self.make_record('photo.png', buffer.getvalue(), 'image/png')
        photo_base = f'/verwaltung/patienten/{self.customer.pk}/datei/{photo.public_id}/'
        response = self.client.get(photo_base + 'vorschau/')
        self.assertEqual(response['X-Preview-State'], 'ready')
        self.assertLessEqual(Image.open(io.BytesIO(response.content)).width, 520)
        text = self.make_record('note.txt', b'<script>alert(1)</script>', 'text/plain')
        response = self.client.get(f'/verwaltung/patienten/{self.customer.pk}/datei/{text.public_id}/ansicht/')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_corrupt_pdf_and_missing_files_have_clear_fallbacks(self):
        Path(self.temp.name, self.record.stored_name).write_bytes(b'%PDF broken')
        response = self.client.get(self.base + 'ansicht/')
        self.assertContains(response, 'keine Vorschau erstellt')
        response = self.client.get(self.base + 'vorschau/')
        self.assertEqual(response['X-Preview-State'], 'unavailable')
        Path(self.temp.name, self.record.stored_name).unlink()
        response = self.client.get(self.base + 'ansicht/')
        self.assertContains(response, 'derzeit nicht verfügbar')

    def test_previews_obey_login_customer_scope_and_doctor_record_access(self):
        other = Customer.objects.create(first_name='Other', last_name='Example', email='other@example.invalid')
        self.assertEqual(self.client.get(f'/verwaltung/patienten/{other.pk}/datei/{self.record.public_id}/vorschau/').status_code, 404)
        staff = StaffMember.objects.create(display_name='Qamar Hameed', role='doctor', active=True)
        doctor = get_user_model().objects.create_user('preview-doctor', is_staff=True)
        AdminAccessProfile.objects.create(user=doctor, staff=staff, view_only=True)
        self.client.force_login(doctor)
        for endpoint in ('ansicht/', 'vorschau/'):
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 404)
        from .models import DoctorPatientAccess
        DoctorPatientAccess.objects.create(staff=staff, customer=self.customer)
        self.record.uploaded_by = doctor
        self.record.save(update_fields=['uploaded_by'])
        for endpoint in ('ansicht/', 'vorschau/'):
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 200)
        self.client.logout()
        for endpoint in ('ansicht/', 'vorschau/'):
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 302)

    @patch('booking.app_management_views._api', return_value={'ok': True})
    def test_record_cards_show_lazy_thumbnail_and_same_tab_link(self, api):
        session = self.client.session
        session['aplus_app_admin'] = True
        session['aplus_admin_authorization'] = 'Bearer synthetic-test'
        session.save()
        response = self.client.get(f'/verwaltung/app/patients/?customer={self.customer.pk}&tab=records')
        self.assertContains(response, self.base + 'vorschau/')
        self.assertContains(response, self.base + 'ansicht/')
        self.assertContains(response, 'loading="lazy"')
        self.assertNotContains(response, self.base + '" target="_blank"')
