import json
import base64
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .models import Appointment, BlockedPeriod, Customer, MobileStaffCancellation, PatientRecord, Service, StaffMember, WorkingHour


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
        (self.day, self.service, self.doctor, self.other, self.patient,
         self.outside, self.own, self.foreign) = fixture()
        self.identity = {'id': 42, 'role': 'admin'}
        mocked = patch('booking.mobile_staff_api._verify', side_effect=lambda req: (self.identity, 200))
        mocked.start()
        self.addCleanup(mocked.stop)

    def post(self, endpoint, **data):
        data.setdefault('key', str(uuid4()))
        return self.client.post('/api/mobile/staff/'+endpoint+'/', json.dumps(data), content_type='application/json')

    def test_calendar_with_no_bearer_is_unauthorized(self):
        with patch('booking.mobile_staff_api._verify', return_value=(None,401)):
            self.assertEqual(self.client.get('/api/mobile/staff/catalog/').status_code, 401)

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
            content.close()

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

    def test_full_patient_history_can_be_paged_beyond_initial_list(self):
        for index in range(34):
            start = timezone.make_aware(datetime.combine(self.day + timedelta(days=index+2), time(13)))
            Appointment.objects.create(
                staff=self.doctor, customer=self.patient, service=self.service,
                starts_at=start, ends_at=start + timedelta(minutes=30), status='confirmed',
            )
            PatientRecord.objects.create(
                customer=self.patient, title=f'QA case {index}', kind='note',
            )
        path = f'/api/mobile/staff/patient/{self.patient.pk}/'
        first = self.client.get(path).json()
        second = self.client.get(path+'?page=2&appointment_page=2').json()
        self.assertEqual(len(first['appointments']), 30)
        self.assertEqual(len(second['appointments']), 5)
        self.assertTrue(first['has_more_appointments'])
        self.assertFalse(second['has_more_appointments'])
        self.assertEqual(len(first['records']), 30)
        self.assertEqual(len(second['records']), 4)
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertTrue({r['id'] for r in first['records']}.isdisjoint(
            {r['id'] for r in second['records']}))

    def test_availability_and_notes_respect_existing_bookings(self):
        values = dict(operation='create',staff_id=self.doctor.pk,date=self.day.isoformat(),start='10:00',end='10:30',text='Internal')
        self.assertEqual(self.post('block',kind='block',**values).status_code,409)
        self.assertEqual(self.post('block',kind='note',**values).status_code,200)
        change = self.post('availability',operation='daily',staff_id=self.doctor.pk,date=self.day.isoformat(),closed=True)
        self.assertEqual(change.status_code,200)
        day = self.client.get(f'/api/mobile/staff/calendar/?start={self.day}&days=1').json()
        self.assertEqual(next(row['ranges'] for row in day['availability'] if row['staff_id']==self.doctor.pk),[])


    def test_admin_can_edit_legacy_blocks_without_mobile_creation_receipt(self):
        start = timezone.make_aware(datetime.combine(self.day, time(14)))
        legacy = BlockedPeriod.objects.create(
            staff=self.doctor, starts_at=start, ends_at=start + timedelta(hours=2),
            reason='[BLOCKNOTE][ALL] Existing desktop block',
        )
        url = f'/api/mobile/staff/calendar/?start={self.day}&days=1'
        block = next(row for row in self.client.get(url).json()['blocks'] if row['id'] == legacy.pk)
        self.assertTrue(block['editable'])
        result = self.post(
            'block', operation='update', id=legacy.pk, revision=block['revision'],
            staff_id=self.doctor.pk, date=self.day.isoformat(), end_date=self.day.isoformat(),
            start='15:00', end='17:00', kind='block', text='Rescheduled by admin',
        )
        self.assertEqual(result.status_code, 200, result.content)
        legacy.refresh_from_db()
        self.assertIn('[ALL]', legacy.reason)
        self.assertEqual(timezone.localtime(legacy.starts_at).strftime('%H:%M'), '15:00')
        # A stale mobile view cannot overwrite a concurrent calendar change.
        self.assertEqual(self.post(
            'block', operation='delete', id=legacy.pk, staff_id=self.doctor.pk,
            revision=block['revision'],
        ).status_code, 409)
        self.identity.update({'id': 84, 'role': 'doctor'})
        doctor_view = next(row for row in self.client.get(url).json()['blocks'] if row['id'] == legacy.pk)
        self.assertFalse(doctor_view['editable'])
        self.assertEqual(self.post(
            'block', operation='delete', id=legacy.pk, staff_id=self.doctor.pk,
            revision=doctor_view['revision'],
        ).status_code, 403)

    def test_admin_override_survives_import_and_deleted_block_does_not_resurrect(self):
        import os
        from .management.commands.sync_simplybook_notes import _marker
        from .models import MobileStaffBlockOverride
        ariane = StaffMember.objects.create(display_name='Frau Ariane Regaei')
        start = timezone.make_aware(datetime.combine(self.day, time(15)))
        marker = _marker(712)
        legacy = BlockedPeriod.objects.create(
            staff=ariane, starts_at=start, ends_at=start + timedelta(hours=1),
            reason='[BLOCKNOTE][STAFF] External note' + marker,
        )
        url = f'/api/mobile/staff/calendar/?start={self.day}&days=1'
        block = next(row for row in self.client.get(url).json()['blocks'] if row['id'] == legacy.pk)
        self.assertTrue(block['editable'])
        self.assertTrue(block['source_managed'])
        self.assertNotIn(marker, block['text'])
        result = self.post(
            'block', operation='update', id=legacy.pk, revision=block['revision'],
            staff_id=ariane.pk, date=self.day.isoformat(), end_date=self.day.isoformat(),
            start='17:00', end='18:00', kind='block', text='Adjusted locally',
        )
        self.assertEqual(result.status_code, 200, result.content)
        override = MobileStaffBlockOverride.objects.get(source_marker=marker)
        self.assertEqual(override.actor_id, 42)
        self.assertFalse(override.deleted)
        legacy.refresh_from_db()
        self.assertEqual(legacy.reason.count(marker), 1)
        remote = [{
            'id': 712, 'note': 'External note', 'time_blocked': True,
            'start_date_time': self.day.strftime('%Y-%m-%d') + ' 15:00:00',
            'end_date_time': self.day.strftime('%Y-%m-%d') + ' 16:00:00',
        }]
        env = {'SIMPLYBOOK_COMPANY_LOGIN': 'test', 'SIMPLYBOOK_USER_LOGIN': 'test',
               'SIMPLYBOOK_USER_PASSWORD': 'test'}
        with patch.dict(os.environ, env), patch(
            'booking.management.commands.sync_simplybook_notes._request_json',
            side_effect=[{'token': 'synthetic'}, remote],
        ):
            call_command('sync_simplybook_notes', suppress_conflict_alerts=True)
        legacy.refresh_from_db()
        self.assertEqual(timezone.localtime(legacy.starts_at).strftime('%H:%M'), '17:00')
        revision = next(row for row in self.client.get(url).json()['blocks'] if row['id'] == legacy.pk)['revision']
        self.assertEqual(self.post(
            'block', operation='delete', id=legacy.pk, staff_id=ariane.pk, revision=revision,
        ).status_code, 200)
        self.assertTrue(MobileStaffBlockOverride.objects.get(source_marker=marker).deleted)
        with patch.dict(os.environ, env), patch(
            'booking.management.commands.sync_simplybook_notes._request_json',
            side_effect=[{'token': 'synthetic'}, remote],
        ):
            call_command('sync_simplybook_notes', suppress_conflict_alerts=True)
        self.assertFalse(BlockedPeriod.objects.filter(staff=ariane, reason__endswith=marker).exists())


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

        with patch('booking.mobile_staff_api._verify', return_value=({'id':42,'role':'admin'},200)):
            with ThreadPoolExecutor(max_workers=2) as executor:
                self.assertEqual(sorted(executor.map(lambda _: post(), range(2))),[200,409])
