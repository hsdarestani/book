from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock
from django.test import TestCase
from django.utils import timezone
from booking.models import Appointment, Customer, Service, StaffMember
from booking.simplybook_outbound import reconcile_existing, sync_existing, SyncConflict, SERVICE_MAP, _verify_catalog, _additional_answers

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
            'getClientList':[self.contact],'getClientInfo':self.contact,
            'isPluginActivated':False,'getAdditionalFields':[],
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

    def test_all_nine_live_catalog_services_map_to_correct_remote_id(self):
        expected = {'aesthetische-erstberatung':8,'botox-neupatient':2,'botox-bestandspatient':10,
                    'hyaluron':3,'infusionstherapie':4,'injektionslipolyse':11,
                    'kontrolltermin':9,'laser-haarentfernung':5,'rf-microneedling':6}
        self.assertEqual({k:v[0] for k,v in SERVICE_MAP.items()},expected)
        self.responses['getEventList']=[{'id':str(i),'name':name,'is_active':'1'} for i,name in SERVICE_MAP.values()]
        for slug,remote_id in expected.items():
            self.item.service.slug=slug
            self.assertEqual(_verify_catalog(self.call,self.item),remote_id)
        self.item.service.slug='unmapped-service'
        with self.assertRaises(SyncConflict):
            _verify_catalog(self.call,self.item)

    def test_additional_answers_sent_by_live_field_id(self):
        self.item.returning_customer=True
        self.item.referral_source='Google'
        self.item.save(update_fields=['returning_customer','referral_source'])
        self.responses['isPluginActivated']=True
        self.responses['getAdditionalFields']=[
            {'name':'returning-id','title':' Warst du schon einmal bei uns?','values':'Ja,Nein'},
            {'name':'referral-id','title':'Wie bist du auf uns aufmerksam geworden?','values':'Google,Sonstiges'},
        ]
        self.assertEqual(sync_existing(self.item.pk,apply=True,call=self.call)['result'],'linked')
        args=[c.args[1] for c in self.call.call_args_list if c.args[0]=='book'][0]
        self.assertEqual(args[8],{'returning-id':'Ja','referral-id':'Google'})

    def test_unanswered_mandatory_field_never_mutates_source(self):
        self.responses['isPluginActivated']=True
        self.responses['getAdditionalFields']=[{'name':'interest-id','title':'Für welche Behandlung interessierst du dich?','values':'Botox-Behandlung,RF-Microneedling','required':True}]
        with self.assertRaisesRegex(SyncConflict,'source_additional_answer_required'):
            sync_existing(self.item.pk,apply=True,call=self.call)
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state,'')
        self.assertNotIn('book',[c.args[0] for c in self.call.call_args_list])

    def test_optional_unanswered_fields_are_not_fabricated(self):
        self.responses['isPluginActivated']=True
        self.responses['getAdditionalFields']=[{'name':'referral-id','title':'Wie bist du auf uns aufmerksam geworden?','values':'Google,Sonstiges'}]
        self.assertEqual(_additional_answers(self.call,self.item,5),{'referral-id':''})

    def quarantine_booking(self):
        self.item.simplybook_sync_state = 'review'
        self.item.simplybook_client_id = '31'
        self.item.simplybook_event_id = '5'
        self.item.save(update_fields=['simplybook_sync_state','simplybook_client_id','simplybook_event_id'])

    def test_reconciliation_leaves_no_match_in_review(self):
        self.quarantine_booking()
        self.assertEqual(reconcile_existing(self.item.pk, apply=True, call=self.call),
                         {'result': 'no_confirmed_remote_booking'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state, 'review')
        self.assertIsNone(self.item.simplybook_booking_id)
        self.assertFalse({'book', 'addClient', 'editBook', 'cancelBooking'} &
                         {call.args[0] for call in self.call.call_args_list})

    def test_reconciliation_validates_and_links_exact_match_once_without_remote_write(self):
        self.quarantine_booking()
        self.responses['getBookings'] = [self.detail]
        self.assertEqual(reconcile_existing(self.item.pk, call=self.call), {'result': 'confirmed_remote_booking'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state, 'review')
        self.assertEqual(reconcile_existing(self.item.pk, apply=True, call=self.call),
                         {'result': 'linked', 'source_booking_id': '92'})
        self.assertEqual(reconcile_existing(self.item.pk, apply=True, call=self.call), {'result': 'already_linked'})
        self.assertFalse({'book', 'addClient', 'editBook', 'cancelBooking'} &
                         {call.args[0] for call in self.call.call_args_list})

    def test_reconciliation_refuses_ambiguous_remote_bookings(self):
        self.quarantine_booking()
        self.responses['getBookings'] = [self.detail, {**self.detail, 'id': '93'}]
        with self.assertRaisesRegex(SyncConflict, 'duplicate_source_bookings'):
            reconcile_existing(self.item.pk, apply=True, call=self.call)
        self.item.refresh_from_db()
        self.assertEqual(self.item.simplybook_sync_state, 'review')

    def test_legacy_web_false_cannot_supply_required_answer(self):
        self.item.source = 'web'
        self.item.save(update_fields=['source'])
        self.responses['isPluginActivated'] = True
        self.responses['getAdditionalFields'] = [
            {'name': 'returning-id', 'title': 'Warst du schon einmal bei uns?',
             'values': 'Ja,Nein', 'required': True},
        ]
        with self.assertRaisesRegex(SyncConflict, 'source_additional_answer_required'):
            sync_existing(self.item.pk, apply=True, call=self.call)
        self.assertNotIn('book', [call.args[0] for call in self.call.call_args_list])
