from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch
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
            'getBookingDetails':self.detail,'calculateEndTime':self.detail['end_date_time']}
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
    def test_legacy_remote_readback_can_select_one_verified_client_from_multiple_links(self):
        from .models import SimplyBookClientLink
        from .simplybook_writeback import _identity

        self.item.service.slug = 'simplybook-event-2'
        links = ['50', '51']
        for external in links:
            SimplyBookClientLink.objects.get_or_create(external_client_id=external, customer=self.item.customer)
        self.assertEqual(_identity(self.item, {'client_id':'51'}), (2, 51))
        with self.assertRaisesRegex(SyncConflict, 'source_client_not_verified'):
            _identity(self.item, {'client_id':'52'})

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

    def test_explicit_negative_answer_is_preserved_in_queued_booking(self):
        self.item.returning_customer_answered = True
        self.item.referral_source = 'Google'
        self.item.simplybook_sync_state = 'queued'
        self.item.save(update_fields=['returning_customer_answered','referral_source','simplybook_sync_state'])
        self.responses['isPluginActivated'] = True
        self.responses['getAdditionalFields'] = [
            {'name':'returning-id','title':'Warst du schon einmal bei uns?','values':'Ja,Nein','required':True},
            {'name':'referral-id','title':'Wie bist du auf uns aufmerksam geworden?','values':'Google,Sonstiges','required':True},
        ]
        self.assertEqual(sync_existing(self.item.pk,apply=True,call=self.call)['result'],'linked')
        args=[c.args[1] for c in self.call.call_args_list if c.args[0]=='book'][0]
        self.assertEqual(args[8],{'returning-id':'Nein','referral-id':'Google'})

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


    @patch.dict('os.environ', {'SIMPLYBOOK_ADMIN_WRITEBACK_ENABLED': 'true'})
    def test_buffered_source_lifecycle_preserves_local_span_and_link(self):
        from booking.clinical_time import add_elapsed
        from booking.simplybook_writeback import change_locked, source_editable

        self.item.treatment_minutes_at_booking = 45
        self.item.save(update_fields=['treatment_minutes_at_booking'])
        remote_end = self.day + ' 16:45:00'
        self.detail['end_date_time'] = remote_end
        self.responses['calculateEndTime'] = remote_end
        self.assertEqual(sync_existing(self.item.pk, apply=True, call=self.call)['result'], 'linked')
        self.item.refresh_from_db()
        self.assertEqual(self.item.reserved_duration, timedelta(minutes=55))
        self.assertEqual(self.item.simplybook_remote_ends_at, add_elapsed(self.item.starts_at, timedelta(minutes=45)))
        self.assertTrue(source_editable(self.item))
        self.assertEqual(sync_existing(self.item.pk, apply=True, call=self.call)['result'], 'already_linked')

        start = add_elapsed(self.item.starts_at, timedelta(hours=2, minutes=10))
        self.responses['getStartTimeMatrix'][self.day].append('18:10:00')
        def remote(method, args):
            if method == 'editBook':
                self.detail.update(start_date_time=self.day + ' 18:10:00', end_date_time=self.day + ' 18:55:00')
                return True
            if method == 'cancelBooking':
                self.detail.update(is_confirmed=False, is_cancelled=True)
                return True
            return self.responses[method]
        self.call.side_effect = remote
        self.assertTrue(change_locked(self.item, starts_at=start, call=self.call))
        self.assertEqual(self.item.starts_at, start)
        self.assertEqual(self.item.reserved_duration, timedelta(minutes=55))
        self.assertTrue(change_locked(self.item, cancel=True, call=self.call))
        self.assertFalse(source_editable(self.item))
        self.assertEqual(self.item.simplybook_booking_id, '92')
        writes = [step.args[0] for step in self.call.call_args_list if step.args[0] in {'book', 'editBook', 'cancelBooking'}]
        self.assertEqual(writes, ['book', 'editBook', 'cancelBooking'])


    def test_booking_answers_use_only_completed_visits_and_verified_referral(self):
        from booking.simplybook_outbound import patient_booking_answers

        now = timezone.now()
        self.assertEqual(patient_booking_answers(self.customer, now=now), (False, 'Google'))
        self.item.starts_at, self.item.ends_at = now - timedelta(days=2), now - timedelta(days=1)
        self.item.status = 'cancelled'
        self.item.referral_source = 'Freunde und Bekannten'
        self.item.returning_customer_answered = True
        self.item.save()
        self.assertEqual(patient_booking_answers(self.customer, now=now), (False, 'Freunde und Bekannten'))
        self.item.status = 'completed'
        self.item.save(update_fields=['status'])
        self.assertEqual(patient_booking_answers(self.customer, now=now), (True, 'Freunde und Bekannten'))


    def test_live_reservation_response_parses_reserved_and_busy_time(self):
        from booking.simplybook_outbound import source_slots

        self.responses['getReservedTimeIntervals'] = {self.day: [
            {'type': 'reserved', 'intervals': [{'from': '15:30', 'to': '16:00'}]},
            {'type': 'busy_time', 'intervals': [{'from': '23:00', 'to': '24:00'}]},
        ]}
        slots, blocks = source_slots(self.call, 5, self.day, self.day)
        self.assertEqual(slots[self.day][0].strftime('%H:%M'), '16:00')
        self.assertEqual([end - start for start, end in blocks],
                         [timedelta(minutes=30), timedelta(hours=1)])
