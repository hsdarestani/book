"""Writeback isolation tests: no actual SimplyBook request and no patient notifications."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Appointment, Customer, Service, StaffMember, SimplyBookClientLink
from .simplybook_writeback import SourceConflict, SourceUnavailable, write_existing_booking
from .mobile_staff_api import _save_synced_appointment


class SimplyBookWritebackTests(TestCase):
    def setUp(self):
        tz=ZoneInfo('Europe/Berlin')
        self.start=timezone.now().astimezone(tz).replace(hour=11,minute=0,second=0,microsecond=0)+timedelta(days=9)
        self.end=self.start+timedelta(minutes=30)
        self.customer=Customer.objects.create(first_name='Synthetic',last_name='QA',email='no-real-patient@example.test')
        self.staff=StaffMember.objects.create(display_name='A+ Esthetic (SimplyBook #8)',role='team')
        self.service=Service.objects.create(name='Synthetic service',slug='simplybook-event-7',duration_minutes=30,bookable=False)
        self.staff.services.add(self.service)
        self.appointment=Appointment.objects.create(customer=self.customer,staff=self.staff,service=self.service,
            starts_at=self.start,ends_at=self.end,status='confirmed',idempotency_key='simplybook-501')
        SimplyBookClientLink.objects.create(customer=self.customer,external_client_id='101',
             source_name='Synthetic QA')
        self.before=self.detail(self.start,self.end)

    @staticmethod
    def detail(start,end,confirmed=True):
        return {'id':501,'event_id':7,'unit_id':8,'client_id':101,
                'client_time_offset':0,
                'start_date_time':start.strftime('%Y-%m-%d %H:%M:%S'),
                'end_date_time':end.strftime('%Y-%m-%d %H:%M:%S'),
                'is_confirmed':confirmed}

    def test_flag_off_prevents_remote_auth(self):
        with patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'false'}),patch(
            'booking.simplybook_writeback._remote_call') as remote:
            with self.assertRaises(SourceConflict):
                write_existing_booking(self.appointment,operation='cancel')
            remote.assert_not_called()

    @patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'true'})
    def test_remote_edit_is_source_first_uses_exact_source_ids_then_reads_back(self):
        changed_start=self.start+timedelta(minutes=30)
        changed_end=self.end+timedelta(minutes=30)
        with patch('booking.simplybook_writeback._session',return_value={'fake':'token'}),patch(
            'booking.simplybook_writeback._remote_call',side_effect=[
              self.before,True,self.detail(changed_start,changed_end)]) as call:
            write_existing_booking(self.appointment,operation='reschedule',start=changed_start,end=changed_end)
        self.assertEqual([x.args[0] for x in call.call_args_list],
                         ['getBookingDetails','editBook','getBookingDetails'])
        fields=call.call_args_list[1].args[1]
        self.assertEqual(fields[:4],[501,7,8,101])
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.starts_at,self.start)

    @patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'true'})
    def test_source_changed_rejects_before_remote_mutation(self):
        stale=self.detail(self.start+timedelta(hours=1),self.end+timedelta(hours=1))
        with patch('booking.simplybook_writeback._session',return_value={'fake':'token'}),patch(
            'booking.simplybook_writeback._remote_call',return_value=stale) as remote:
            with self.assertRaises(SourceConflict):
                write_existing_booking(self.appointment,operation='reschedule',start=self.start+timedelta(minutes=30),
                                       end=self.end+timedelta(minutes=30))
            self.assertEqual(remote.call_count,1)

    @patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'true'})
    def test_remote_failure_never_writes_local_appointment(self):
        new_start=self.start+timedelta(minutes=30)
        with patch('booking.mobile_staff_api.write_existing_booking',
                   side_effect=SourceUnavailable('Remote failed')):
            from .mobile_staff_api import CommandConflict
            with self.assertRaises(CommandConflict):
                _save_synced_appointment({'operation':'update','revision':self.appointment.updated_at.isoformat(),
                    'staff_id':self.staff.pk,'service_id':self.service.pk,'customer_id':self.customer.pk,
                    'status':'confirmed','date':new_start.date().isoformat(),'start':new_start.strftime('%H:%M')},
                    {'role':'admin'},self.appointment)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.starts_at,self.start)
        self.assertEqual(self.appointment.status,'confirmed')

    @patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'true'})
    def test_confirmed_cancellation_only_updates_book_after_source(self):
        from .models import MobileStaffCancellation
        payload={'operation':'cancel','revision':self.appointment.updated_at.isoformat()}
        with patch('booking.mobile_staff_api.write_existing_booking',return_value=self.detail(
                self.start,self.end,False)) as source:
            _save_synced_appointment(payload,{'role':'admin'},self.appointment)
            source.assert_called_once()
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,'cancelled')
        self.assertFalse(MobileStaffCancellation.objects.exists())

    @patch.dict(os.environ,{'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED':'true'})
    def test_doctor_cannot_change_source_and_patient_must_match(self):
        from .mobile_staff_api import _save_synced_appointment
        from .models import SimplyBookClientLink
        with patch('booking.mobile_staff_api.write_existing_booking') as write:
            with self.assertRaises(PermissionError):
                _save_synced_appointment({'operation':'cancel'}, {'role':'doctor'},self.appointment)
            write.assert_not_called()
        SimplyBookClientLink.objects.all().delete()
        with patch('booking.simplybook_writeback._session',return_value={'fake':'token'}),patch(
            'booking.simplybook_writeback._remote_call',return_value=self.before) as remote:
            with self.assertRaises(SourceConflict):
                write_existing_booking(self.appointment,operation='cancel')
            self.assertEqual(remote.call_count,1)
