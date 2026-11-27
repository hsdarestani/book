import json
import base64
from io import BytesIO
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .clinical_time import CLINIC_TZ
from .models import Appointment, BlockedPeriod, Customer, MobileStaffCancellation, OfficeIntakeForm, PatientRecord, Service, SimplyBookClientLink, StaffMember, WorkingHour


def fixture():
    day = timezone.localdate() + timedelta(days=1)
    service = Service.objects.create(name='Mobile consultation', slug='mobile-qa', duration_minutes=30, buffer_minutes=0)
    doctor = StaffMember.objects.get_or_create(display_name='Qamar Hameed', defaults={'role': 'doctor'})[0]
    BlockedPeriod.objects.filter(staff=doctor, reason__contains='Keine Online-Termine bis 31.12.2026').delete()
    other = StaffMember.objects.create(display_name='Another provider')
    patient = Customer.objects.create(first_name='Own', last_name='Patient', email='own@example.test')
    outside = Customer.objects.create(first_name='Other', last_name='Patient', email='other@example.test')
    appts = []
    for staff, person in ((doctor, patient), (other, outside)):
        staff.services.add(service)
        WorkingHour.objects.create(staff=staff, weekday=day.weekday(), start_time=time(9), end_time=time(19))
        start = timezone.make_aware(datetime.combine(day,time(10)))
        appts.append(Appointment.objects.create(
            staff=staff, customer=person, service=service, starts_at=start,
            ends_at=start+timedelta(minutes=30), status='confirmed',
        ))
    return day, service, doctor, other, patient, outside, *appts


class WorkspaceTests(TestCase):
    def setUp(self):
        # A threaded PostgreSQL lock regression in this module closes its
        # worker connections; heal a stale pooled wrapper before using fixtures.
        if not connection.is_usable():
            connection.close()
            connection.ensure_connection()
        (self.day, self.service, self.doctor, self.other, self.patient,
         self.outside, self.own, self.foreign) = fixture()
        self.identity = {'id': 42, 'role': 'admin'}
        mocked = patch('booking.mobile_staff_api._verify', side_effect=lambda req: (self.identity, 200))
        mocked.start()
        self.addCleanup(mocked.stop)
        # Never relay synthetic test bookings or patient information to live
        # integrations, including the retired legacy notification host.
        notifications = patch('booking.notifications._post_internal',return_value={'ok':True})
        notifications.start()
        self.addCleanup(notifications.stop)
        booking_email = patch('booking.mobile_staff_api.send_customer_booking_email')
        booking_email.start()
        self.addCleanup(booking_email.stop)

    def post(self, endpoint, **data):
        data.setdefault('key', str(uuid4()))
        return self.client.post('/api/mobile/staff/'+endpoint+'/', json.dumps(data), content_type='application/json')

    def test_calendar_with_no_bearer_is_unauthorized(self):
        with patch('booking.mobile_staff_api._verify', return_value=(None,401)):
            self.assertEqual(self.client.get('/api/mobile/staff/catalog/').status_code, 401)

    def test_staff_contact_edits_keep_identity_and_are_visible_to_book_administrators(self):
        from .app_admin_api import _appointment_payload, _customer_payload

        endpoint = f'/api/mobile/staff/patient/{self.patient.pk}/contact/'
        link = SimplyBookClientLink.objects.create(external_client_id='synthetic-contact',
            customer=self.patient, source_email=self.patient.email, source_phone='03023125000')
        initial = self.client.get(endpoint)
        self.assertIn('no-store', initial.headers['Cache-Control'])
        revision = initial.json()['patient']['contact_revision']
        changes = {'revision':revision, 'phone':'+493023125000', 'email':'updated@example.test'}
        count = Customer.objects.count()
        for _ in range(2):
            saved = self.client.post(endpoint, changes, content_type='application/json')
            self.assertEqual(saved.status_code, 200)
        profile = self.client.get(f'/api/mobile/staff/patient/{self.patient.pk}/').json()['patient']
        self.assertEqual((profile['id'], profile['email'], profile['phone']),
                         (self.patient.pk, changes['email'], changes['phone']))
        self.assertEqual(self.client.get('/api/mobile/staff/patients/?q=updated@example.test').json()['items'][0]['id'], self.patient.pk)
        self.patient.refresh_from_db()
        self.assertEqual(Customer.objects.count(), count)
        self.assertEqual((self.patient.email, self.patient.phone), ('own@example.test', ''))
        self.assertEqual(_customer_payload(self.patient)['email'], changes['email'])
        self.own.refresh_from_db()
        self.assertEqual(_appointment_payload(self.own)['customer_phone'], changes['phone'])
        link.refresh_from_db()
        self.assertEqual((link.customer_id, link.source_email, link.source_phone),
                         (self.patient.pk, 'own@example.test', '03023125000'))
        self.assertEqual(self.client.post(endpoint, {**changes, 'email':'stale@example.test'},
                                         content_type='application/json').status_code, 409)
        clear = {'revision':saved.json()['patient']['contact_revision'], 'phone':'', 'email':''}
        self.assertEqual(self.client.post(endpoint, clear, content_type='application/json').status_code, 200)
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.contact_email, self.patient.contact_phone), ('', ''))

    def test_staff_contact_permissions_validation_and_identity_collision(self):
        endpoint = f'/api/mobile/staff/patient/{self.patient.pk}/contact/'
        revision = self.client.get(endpoint).json()['patient']['contact_revision']
        for data, status in [
            ({'phone':'06900000'}, 400), ({'email':'invalid'}, 400),
            ({'email':'somebody@invalid.local'}, 400), ({'phone':123}, 400),
            ({'email':'changed@example.test', 'customer_id':self.outside.pk}, 400),
            ({'email':'OTHER@example.test'}, 409),
        ]:
            result = self.client.post(endpoint, {'revision':revision, **data}, content_type='application/json')
            self.assertEqual(result.status_code, status)
        self.identity['role'] = 'doctor'
        self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assertEqual(self.client.get(f'/api/mobile/staff/patient/{self.outside.pk}/contact/').status_code, 404)
        self.assertEqual(self.client.post(endpoint, {'revision':revision, 'phone':'+493023125000'},
                                         content_type='application/json').status_code, 403)
        with patch('booking.mobile_staff_api._verify', return_value=(None,401)):
            self.assertEqual(self.client.get(endpoint).status_code, 401)
        self.patient.refresh_from_db()
        self.assertIsNone(self.patient.contact_phone_override)

    def test_premium_overview_and_private_signed_form_routes(self):
        overview = self.client.get('/api/mobile/staff/overview/').json()
        self.assertGreaterEqual(overview['upcoming_count'], 2)
        self.assertTrue(any(row['id']==self.doctor.pk for row in overview['provider_today']))
        from PIL import Image
        signature = BytesIO()
        Image.new('RGB',(20,10),'white').save(signature,format='PNG')
        form = OfficeIntakeForm.objects.create(source_id=uuid4(), status='review',
            payload={'identity':{'first_name':'Own','last_name':'Patient','email':self.patient.email},
                     'answers':{'allergies':'Synthetic'},'consent_text':'Synthetic consent'},
            signature_png='data:image/png;base64,'+base64.b64encode(signature.getvalue()).decode())
        root='/api/mobile/staff/forms/'
        listing=self.client.get(root+'?q=Own&status=review').json()
        self.assertEqual(listing['items'][0]['id'],form.pk)
        self.assertNotIn('signature_png',listing['items'][0])
        detail=self.client.get(root+str(form.pk)+'/').json()['submission']
        self.assertEqual(detail['answers']['allergies'],'Synthetic')
        self.assertEqual(self.client.get(root+str(form.pk)+'/pdf/').content[:5],b'%PDF-')
        self.identity['role']='doctor'
        for path in (root,root+str(form.pk)+'/',root+str(form.pk)+'/pdf/'):
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.post('forms/'+str(form.pk)+'/link',customer_id=self.patient.pk,confirmed_same_patient=True).status_code,403)
        self.identity['role']='admin'
        self.assertEqual(self.post('forms/'+str(form.pk)+'/link',customer_id=self.patient.pk,confirmed_same_patient=False).status_code,409)
        with tempfile.TemporaryDirectory() as directory, override_settings(PATIENT_FILES_ROOT=directory):
            linked=self.post('forms/'+str(form.pk)+'/link',customer_id=self.patient.pk,confirmed_same_patient=True)
            self.assertEqual(linked.status_code,200,linked.content)
            form.refresh_from_db()
            self.assertEqual(form.customer_id,self.patient.pk)
            self.assertIsNotNone(form.record_id)
            self.assertEqual(form.reviewed_by.username,'aplus_app_admin_42')

    def test_doctor_scope_applies_to_calendar_people_records_and_writes(self):
        self.identity['role'] = 'doctor'
        response = self.client.get(f'/api/mobile/staff/calendar/?start={self.day}&days=7')
        self.assertEqual(response.status_code,200)
        self.assertEqual([row['id'] for row in response.json()['appointments']], [self.own.pk])
        visible = PatientRecord.objects.create(customer=self.patient, appointment=self.own, title='Visible', kind='note')
        hidden = PatientRecord.objects.create(customer=self.patient, title='Hidden', kind='note')
        details = self.client.get(f'/api/mobile/staff/patient/{self.patient.pk}/')
        self.assertEqual([row['id'] for row in details.json()['records']], [str(visible.public_id)])
        self.assertEqual(self.client.get(f'/api/mobile/staff/patient/{self.patient.pk}/records/{hidden.public_id}/').status_code,404)
        self.assertEqual(self.client.get(f'/api/mobile/staff/patient/{self.outside.pk}/').status_code,404)
        self.assertEqual(self.post('appointment', operation='cancel',id=self.foreign.pk).status_code,404)
        self.assertEqual(self.post('block', operation='create',staff_id=self.other.pk).status_code,404)
        self.assertEqual(self.post('service',id=self.service.pk,name='Restricted').status_code,403)

    def test_native_pdf_upload_is_scoped_and_idempotent(self):
        self.identity['role'] = 'doctor'
        payload = {'customer_id': self.patient.pk,'filename':'synthetic.pdf',
                   'base64':base64.b64encode(b'%PDF-1.4\\nsynthetic').decode(),'key':str(uuid4())}
        with tempfile.TemporaryDirectory() as directory, override_settings(PATIENT_FILES_ROOT=directory):
            forbidden = self.post('record-upload', **(payload | {'customer_id':self.outside.pk}))
            self.assertEqual(forbidden.status_code, 403)
            uploaded = self.post('record-upload', **payload)
            self.assertEqual(uploaded.status_code, 200, uploaded.content)
            self.assertTrue(self.post('record-upload', **payload).json()['replayed'])
            record = PatientRecord.objects.get(pk=uploaded.json()['id'])
            self.assertEqual(record.customer_id, self.patient.pk)
            self.assertFalse(record.metadata['shared_with_customer'])
            content = self.client.get(f'/api/mobile/staff/patient/{self.patient.pk}/records/{record.public_id}/')
            self.assertEqual(content.status_code, 200)
            # FileResponse.close() sends request_finished. In Django TestCase
            # its close_old_connections receiver may close the still-active
            # class transaction; keep that test fixture connection alive.
            from django.core.signals import request_finished
            from django.db import close_old_connections
            request_finished.disconnect(close_old_connections)
            try:
                content.close()
            finally:
                request_finished.connect(close_old_connections)

    def test_private_photo_and_note_correction_are_scoped_and_revision_safe(self):
        from PIL import Image
        self.identity['role']='doctor'
        photo=BytesIO()
        Image.new('RGB',(40,20),'white').save(photo,format='JPEG')
        data={'customer_id':self.patient.pk,'filename':'synthetic.jpg','base64':base64.b64encode(photo.getvalue()).decode()}
        with tempfile.TemporaryDirectory() as directory, override_settings(PATIENT_FILES_ROOT=directory):
            result=self.post('record-upload',**data)
            self.assertEqual(result.status_code,200,result.content)
            record=PatientRecord.objects.get(pk=result.json()['id'])
            self.assertEqual(record.kind,'photo')
            self.assertFalse(record.metadata['shared_with_customer'])
            self.assertEqual(self.post('record-upload',**(data|{'base64':base64.b64encode(b'not-an-image').decode()})).status_code,400)
        create=self.post('record-note',customer_id=self.patient.pk,title='Test note',note='Original synthetic note')
        self.assertEqual(create.status_code,200)
        note=PatientRecord.objects.get(pk=create.json()['id'])
        payload=self.client.get(f'/api/mobile/staff/patient/{self.patient.pk}/').json()
        revision=next(row['revision'] for row in payload['records'] if row['id']==str(note.public_id))
        correction={'customer_id':self.patient.pk,'record_id':str(note.public_id),'revision':revision,'title':'Corrected note','note':'Corrected synthetic note'}
        self.assertEqual(self.post('record-edit',**correction).status_code,200)
        self.assertEqual(self.post('record-edit',**correction).status_code,409)
        note.refresh_from_db()
        self.assertEqual(note.metadata['native_revisions'][0]['note'],'Original synthetic note')
        self.assertEqual(self.post('record-edit',**(correction|{'customer_id':self.outside.pk})).status_code,403)

    def test_create_replay_collision_and_slot_overlap(self):
        payload = dict(operation='create',staff_id=self.doctor.pk,customer_id=self.patient.pk,
                       service_id=self.service.pk,date=self.day.isoformat(), start='12:00')
        key = str(uuid4())
        first = self.post('appointment',key=key,**payload)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.post('appointment',key=key,**payload).json()['id'], first.json()['id'])
        self.assertEqual(self.post('appointment',key=key,**{**payload,'start':'12:30'}).status_code,409)
        self.assertEqual(self.post('appointment',**payload).status_code,409)

    def test_appointment_update_uses_revision_and_cancellation_uses_durable_reconciliation(self):
        revision = self.own.updated_at.isoformat()
        payload = dict(operation='update',id=self.own.pk,staff_id=self.doctor.pk,customer_id=self.patient.pk,
                       service_id=self.service.pk,date=self.day.isoformat(),start='10:30',status='confirmed',revision=revision)
        self.assertEqual(self.post('appointment',**payload).status_code,200)
        self.assertEqual(self.post('appointment',**payload).status_code,409)
        self.own.refresh_from_db()
        cancel = dict(operation='cancel',id=self.own.pk,revision=self.own.updated_at.isoformat())
        self.assertEqual(self.post('appointment',**cancel).status_code,200)
        self.assertEqual(self.post('appointment',**cancel).status_code,200)
        self.assertEqual(MobileStaffCancellation.objects.count(),1)
        self.own.refresh_from_db()
        self.assertEqual(self.own.status,'cancelled')
        with patch('booking.management.commands.reconcile_mobile_cancellations._post_internal',
                   side_effect=[{'ok':False},{'ok':True}]) as relay:
            call_command('reconcile_mobile_cancellations')
            self.assertIsNone(MobileStaffCancellation.objects.get().completed_at)
            MobileStaffCancellation.objects.update(next_attempt_at=timezone.now())
            call_command('reconcile_mobile_cancellations')
            call_command('reconcile_mobile_cancellations')
            self.assertIsNotNone(MobileStaffCancellation.objects.get().completed_at)
            self.assertEqual(relay.call_count,2)

    def test_manual_app_reminder_is_scoped_and_idempotent(self):
        self.identity['role'] = 'doctor'
        key = str(uuid4())
        with patch('booking.mobile_staff_api.notify_manual_app_reminder', return_value={'ok': True, 'notifications': 1}) as notify:
            self.assertEqual(self.post('appointment-reminder', id=self.foreign.pk).status_code, 404)
            self.assertEqual(self.post('appointment-reminder', id=self.own.pk, key=key).status_code, 200)
            replay = self.post('appointment-reminder', id=self.own.pk, key=key)
            self.assertEqual(replay.status_code, 200)
            self.assertTrue(replay.json()['replayed'])
            notify.assert_called_once()

    def test_uncertain_reminder_is_quarantined_even_with_new_key(self):
        key = str(uuid4())
        with patch('booking.mobile_staff_api.notify_manual_app_reminder', side_effect=TimeoutError) as notify:
            self.assertEqual(self.post('appointment-reminder', id=self.own.pk, key=key).status_code, 409)
            self.assertEqual(self.post('appointment-reminder', id=self.own.pk, key=key).status_code, 409)
            self.assertEqual(self.post('appointment-reminder', id=self.own.pk).status_code, 409)
            notify.assert_called_once()

    def test_external_source_blocks_and_appointments_are_read_only(self):
        from .management.commands.sync_simplybook_notes import _marker
        from .models import MobileStaffCommand
        start = timezone.make_aware(datetime.combine(self.day, time(15)))
        marker = _marker(194)
        synced = BlockedPeriod.objects.create(
            staff=self.doctor, starts_at=start, ends_at=start + timedelta(hours=1),
            reason='[BLOCKNOTE][STAFF] Synced consultation' + marker,
        )
        # Even a stale mobile command receipt must never enable SimplyBook changes.
        MobileStaffCommand.objects.create(
            actor_id=42, key=uuid4(), fingerprint='0'*64, action='block', object_id=synced.pk,
        )
        payload = self.client.get(f'/api/mobile/staff/calendar/?start={self.day}&days=1').json()
        entry = next(x for x in payload['blocks'] if x['id']==synced.pk)
        self.assertFalse(entry['editable'])
        self.assertTrue(entry['source_managed'])
        self.assertEqual(entry['management_system'], 'SimplyBook')
        self.assertNotIn(marker, entry['text'])
        changed = self.post('block',operation='update',id=synced.pk,staff_id=self.doctor.pk,
                            date=self.day.isoformat(),start='16:00',end='17:00',kind='block')
        self.assertEqual(changed.status_code,409)
        self.assertIn('SimplyBook',changed.json()['message'])
        self.assertEqual(self.post('block',operation='delete',id=synced.pk,
                                   staff_id=self.doctor.pk).status_code,409)
        synced.refresh_from_db()
        self.assertEqual(timezone.localtime(synced.starts_at).strftime('%H:%M'),'15:00')
        self.own.idempotency_key='simplybook-194'
        self.own.save(update_fields=['idempotency_key'])
        response=self.post('appointment',operation='cancel',id=self.own.pk,
                           revision=self.own.updated_at.isoformat(),staff_id=self.doctor.pk)
        self.assertEqual(response.status_code,409)
        self.assertIn('SimplyBook',response.json()['message'])
        self.own.refresh_from_db()
        self.assertEqual(self.own.status,'confirmed')
        self.own.idempotency_key = None
        self.own.simplybook_sync_state = 'review'
        self.own.save(update_fields=['idempotency_key', 'simplybook_sync_state'])
        result = self.post('appointment', operation='cancel', id=self.own.pk,
                           revision=self.own.updated_at.isoformat(), staff_id=self.doctor.pk)
        self.assertEqual(result.status_code, 409)

    def test_synced_simplybook_catalog_and_working_hours_cannot_be_mutated(self):
        imported = StaffMember.objects.create(display_name='A+ Esthetic (SimplyBook #7)',role='team')
        source_service = Service.objects.create(name='External treatment',slug='simplybook-event-7',
                                                duration_minutes=30,buffer_minutes=0,bookable=False)
        imported.services.add(source_service)
        catalog=self.client.get('/api/mobile/staff/catalog/').json()
        provider=next(x for x in catalog['providers'] if x['id']==imported.pk)
        service=next(x for x in catalog['services'] if x['id']==source_service.pk)
        self.assertEqual(provider['management_system'],'SimplyBook')
        self.assertTrue(provider['source_managed'])
        self.assertTrue(service['source_managed'])
        self.assertEqual(self.post('service',id=source_service.pk,name='Changed').status_code,409)
        self.assertEqual(self.post('availability',operation='daily',staff_id=imported.pk,
                                   date=self.day.isoformat(),closed=True).status_code,409)
        self.assertEqual(self.post('block',operation='create',staff_id=imported.pk,
                                   date=self.day.isoformat(),start='15:00',end='16:00',kind='block').status_code,409)
        response=self.post('appointment',operation='create',staff_id=imported.pk,
                           customer_id=self.patient.pk,service_id=source_service.pk,
                           date=self.day.isoformat(),start='15:00')
        self.assertEqual(response.status_code,409)
        self.assertEqual(Service.objects.get(pk=source_service.pk).name,'External treatment')

    def test_calendar_preserves_berlin_time_and_booking_duration_after_catalog_edit(self):
        self.service.duration_minutes = 45
        self.service.buffer_minutes = 10
        self.service.save(update_fields=['duration_minutes', 'buffer_minutes'])
        WorkingHour.objects.filter(staff=self.other, weekday=self.day.weekday()).update(end_time=time(21))
        payload = dict(operation='create', staff_id=self.other.pk, customer_id=self.outside.pk,
                       service_id=self.service.pk, date=self.day.isoformat(), start='18:30')
        with timezone.override('Pacific/Honolulu'):
            result = self.post('appointment', **payload)
        self.assertEqual(result.status_code, 200, result.content)
        item = Appointment.objects.get(pk=result.json()['id'])
        self.service.duration_minutes = 55
        self.service.buffer_minutes = 0
        self.service.save(update_fields=['duration_minutes', 'buffer_minutes'])
        with timezone.override('Pacific/Kiritimati'):
            result = self.client.get(f'/api/mobile/staff/calendar/?start={self.day}&days=1')
        entry = next(row for row in result.json()['appointments'] if row['id'] == item.pk)
        self.assertEqual(entry['start'], '18:30')
        self.assertEqual(entry['end'], '19:25')
        self.assertEqual(datetime.fromisoformat(entry['treatment_end_at']).astimezone(CLINIC_TZ).time(), time(19, 15))
        update = dict(payload, operation='update', id=item.pk, revision=item.updated_at.isoformat(),
                      start='18:45', status='confirmed')
        self.assertEqual(self.post('appointment', **update).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.calendar_treatment_end.astimezone(CLINIC_TZ).time(), time(19, 30))
        self.assertEqual(item.ends_at.astimezone(CLINIC_TZ).time(), time(19, 40))

    def test_availability_and_notes_respect_existing_bookings(self):
        values = dict(operation='create',staff_id=self.doctor.pk,date=self.day.isoformat(),start='10:00',end='10:30',text='Internal')
        self.assertEqual(self.post('block',kind='block',**values).status_code,409)
        self.assertEqual(self.post('block',kind='note',**values).status_code,200)
        change = self.post('availability',operation='daily',staff_id=self.doctor.pk,date=self.day.isoformat(),closed=True)
        self.assertEqual(change.status_code,200)
        day = self.client.get(f'/api/mobile/staff/calendar/?start={self.day}&days=1').json()
        self.assertEqual(next(row['ranges'] for row in day['availability'] if row['staff_id']==self.doctor.pk),[])


class WorkspaceConcurrencyTests(TransactionTestCase):
    def test_provider_lock_prevents_concurrent_mobile_overlap(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires PostgreSQL locks')
        day, service, doctor, _, patient, _, _, _ = fixture()
        payload = dict(operation='create',staff_id=doctor.pk,customer_id=patient.pk,service_id=service.pk,
                       date=day.isoformat(),start='14:00')

        def post():
            try:
                return Client().post('/api/mobile/staff/appointment/', json.dumps({**payload,'key':str(uuid4())}),
                                     content_type='application/json').status_code
            finally:
                connections.close_all()

        with (patch('booking.mobile_staff_api._verify', return_value=({'id':42,'role':'admin'},200)),
              patch('booking.mobile_staff_api._notify')):
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sorted(executor.map(lambda _: post(), range(2))),[200,409])
