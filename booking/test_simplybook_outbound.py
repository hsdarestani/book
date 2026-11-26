from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from django.test import TestCase
from django.utils import timezone
from booking.models import Appointment, Customer, Service, StaffMember
from booking.simplybook_outbound import sync_existing, SyncConflict

class SimplyBookOutboundPilotTests(TestCase):
    def setUp(self):
        self.staff=StaffMember.objects.get(display_name='Frau Ariane Regaei')
        self.service=Service.objects.get(slug='laser-haarentfernung')
        self.customer=Customer.objects.create(first_name='Test',last_name='Farahani',email='qa@example.test',phone='+4915112345678')
        day=timezone.localdate()+timedelta(days=30)
        start=datetime.combine(day,datetime.min.time().replace(hour=16),tzinfo=ZoneInfo('Europe/Berlin'))
        self.item=Appointment.objects.create(staff=self.staff,service=self.service,customer=self.customer,
            starts_at=start,ends_at=start+timedelta(minutes=55),status='confirmed',source='app',idempotency_key='qa-request')
        self.day=day.isoformat()
        self.contact={'id':'31','name':'Test Farahani','email':'qa@example.test','phone':'+4915112345678'}
        self.detail={'id':'92','event_id':'5','unit_id':'2','client_id':'31','is_confirmed':'1',
            'start_date_time':self.day+' 16:00:00','end_date_time':self.day+' 16:55:00'}
        self.responses={'getCompanyTimezoneOffset':{'timezone':'Europe/Berlin'},
            'getUnitList':[{'id':'2','is_active':'1'}],
            'getEventList':[{'id':'5','name':'Dauerhafte Haarentfernung  (Alexandrit - Nd:YAG)','is_active':'1'}],
            'getClientList':[self.contact],'getClient':self.contact,
            'getBookings':[],'getStartTimeMatrix':{self.day:['16:00:00']},
            'getReservedTimeIntervals':{self.day:[]},'book':{'require_confirm':False,'bookings':[self.detail]},
            'getBookingDetails':self.detail}
        self.call=Mock(side_effect=lambda m,p:self.responses[m])
    def test_dry_run_never_mutates(self):
        self.assertEqual(sync_existing(self.item.pk,call=self.call)['result'],'preflight_ok')
        self.assertNotIn('book',[x.args[0] for x in self.call.call_args_list])
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state,'')
    def test_readback_links_same_local_uuid_and_keeps_request_key(self):
        self.assertEqual(sync_existing(self.item.pk,apply=True,call=self.call)['result'],'linked')
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_booking_id,'92')
        self.assertEqual(self.item.idempotency_key,'qa-request')
        book=[x.args[1] for x in self.call.call_args_list if x.args[0]=='book']
        self.assertEqual(book[0][4],'16:00:00')
        self.assertEqual(book[0][6],'16:55:00')
        self.assertEqual(sync_existing(self.item.pk,apply=True,call=self.call)['result'],'already_linked')
        self.assertEqual(len([x for x in self.call.call_args_list if x.args[0]=='book']),1)
    def test_uncertain_write_never_retries(self):
        self.responses['getBookingDetails']={}
        with self.assertRaises(SyncConflict):
            sync_existing(self.item.pk,apply=True,call=self.call)
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state,'review')
        with self.assertRaises(SyncConflict):
            sync_existing(self.item.pk,apply=True,call=self.call)
        self.assertEqual(len([x for x in self.call.call_args_list if x.args[0]=='book']),1)
    def test_other_doctor_never_calls_source(self):
        self.staff.display_name='Other doctor'
        self.staff.save()
        with self.assertRaises(SyncConflict):
            sync_existing(self.item.pk,apply=True,call=self.call)
        self.call.assert_not_called()
