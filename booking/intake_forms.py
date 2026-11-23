"""Server-to-server intake ingestion and private patient-file attachment.

All input here comes from the signed A+ Office server, NOT a public endpoint.
Conflicting/ambiguous 3-of-5 matches are never attached to an unrelated file.
"""
import base64
import binascii
import io
import json
import re
import uuid
from datetime import date

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from .internal_api import _authorized, _store_bytes
from .intake_identity import locate_unique_intake_patient, match_score
from .models import Customer, OfficeIntakeForm, PatientRecord

CONSENT_TEXT = (
    "Datenerhebung und Datenschutz – A+ Esthetic\n"
    "A+ Esthetic erhebt und verarbeitet die von Ihnen bereitgestellten personenbezogenen Daten "
    "zur Bearbeitung Ihrer Anfrage, zur Terminverwaltung und zur Erbringung unserer Dienstleistungen.\n"
    "Mit meiner Unterschrift bestätige ich, dass die von mir angegebenen Informationen "
    "nach bestem Wissen richtig und vollständig sind.\n"
    "Die Verarbeitung meiner personenbezogenen Daten erfolgt gemäß den geltenden "
    "Datenschutzbestimmungen, insbesondere der Datenschutz-Grundverordnung (DSGVO). "
    "Die Datenschutzhinweise von A+ Esthetic wurden mir zur Verfügung gestellt."
)

def _json_error(code, status=400):
    return JsonResponse({'ok':False,'error':code},status=status)

def _signature_bytes(raw):
    if not isinstance(raw,str) or not raw.startswith('data:image/png;base64,') or len(raw)>260000:
        raise ValueError('invalid_signature')
    try:
        content=base64.b64decode(raw.split(',',1)[1], validate=True)
    except (ValueError,binascii.Error):
        raise ValueError('invalid_signature')
    if len(content)>190000 or not content.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('invalid_signature')
    return content

def build_intake_pdf(form):
    """Only generated for private staff records; NEVER offered to the submitter."""
    data=form.payload
    identity=data['identity']
    answers=data.get('answers') or {}
    styles=getSampleStyleSheet()
    buf=io.BytesIO()
    pdf=SimpleDocTemplate(buf,pagesize=A4,leftMargin=36,rightMargin=36,topMargin=34,bottomMargin=42)
    story=[Paragraph('A+ Esthetic · Allgemeiner Aufnahmebogen',styles['Heading1']),
           Paragraph('Erfasst am '+form.submitted_at.strftime('%d.%m.%Y %H:%M'),styles['Normal']),Spacer(1,14)]
    readable={
        'first_name':'Vorname','last_name':'Nachname','date_of_birth':'Geburtsdatum',
        'email':'E-Mail','phone':'Telefon','street':'Straße','postal_code':'PLZ',
        'city':'Ort','profession':'Beruf','gender':'Geschlecht',
        'allergies':'Allergien','allergies_notes':'Allergien – Details',
        'diseases':'Erkrankungen','other_diseases':'Weitere Erkrankungen',
        'medications':'Medikamente','medications_notes':'Medikamente – Details',
        'surgeries':'Operationen / Eingriffe','surgeries_notes':'Eingriffe – Details',
        'pregnancy':'Schwangerschaft / Stillzeit','smoking':'Rauchen','cigarettes':'Zigaretten/Tag',
        'alcohol':'Alkohol','alcohol_frequency':'Alkohol pro Woche',
        'interests':'Behandlungsinteressen','expectations':'Erwartungen',
        'prior_treatments':'Frühere Behandlungen','prior_treatments_notes':'Vorbehandlungen',
        'referral':'Auf uns aufmerksam geworden','referral_other':'Weitere Quelle',
        'photo_consultation':'Fotofreigabe Beratung','photo_marketing':'Fotofreigabe Marketing',
    }
    def section(title,values):
        story.append(Paragraph(escape(title),styles['Heading2']))
        for key,value in values.items():
            if value is None or value=='' or value==[]:continue
            rendered=', '.join(str(x) for x in value) if isinstance(value,list) else str(value)
            rendered=rendered[:3000]
            story.append(Paragraph('<b>'+escape(readable.get(key,key))+':</b> '+escape(rendered).replace('\n','<br/>'),styles['Normal']))
            story.append(Spacer(1,5))
        story.append(Spacer(1,9))
    section('Patienteninformationen',identity)
    section('Anamnese und ästhetische Anliegen',answers)
    story.append(Paragraph('Datenerhebung und Datenschutz',styles['Heading2']))
    for line in CONSENT_TEXT.split('\n'):
        story.append(Paragraph(escape(line),styles['Normal']))
        story.append(Spacer(1,5))
    story.append(Spacer(1,12))
    story.append(Paragraph('Digitale Unterschrift',styles['Heading3']))
    try:
        image=Image(io.BytesIO(_signature_bytes(form.signature_png)),width=195,height=80,kind='proportional')
        story.append(image)
    except (ValueError, OSError):
        story.append(Paragraph('Signatur technisch nicht verfügbar.',styles['Normal']))
    pdf.build(story)
    return buf.getvalue()

def attach_private_record(form):
    if not form.customer_id or form.record_id:
        return
    raw=build_intake_pdf(form)
    stored,original,mime,size=_store_bytes(form.customer,'Aufnahmebogen-'+str(form.source_id)+'.pdf',raw,'application/pdf')
    record=PatientRecord.objects.create(
        customer=form.customer, kind='form', title='Allgemeiner Aufnahmebogen',
        note='Vom Patienten digital ausgefüllter Aufnahmebogen und Unterschrift.',
        stored_name=stored,original_name=original,mime_type=mime,file_size=size,
        source='office_intake',external_id=str(form.source_id),
        captured_at=form.submitted_at,metadata={'form_id':form.pk,'shared_with_customer':False})
    form.record=record
    form.save(update_fields=['record'])

@csrf_exempt
@require_POST
def ingest_office_intake(request):
    if not _authorized(request):
        return _json_error('unauthorized',401)
    if len(request.body)>450000:
        return _json_error('too_large',413)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict):raise ValueError
        source_id=uuid.UUID(str(data['source_id']))
        identity=data['identity']
        answers=data['answers']
        if not isinstance(identity,dict) or not isinstance(answers,dict):raise ValueError
        if len(json.dumps(answers,ensure_ascii=False))>80000:raise ValueError
        if not all(str(identity.get(k) or '').strip() for k in
                   ('first_name','last_name','phone','email','date_of_birth')):
            raise ValueError
        email=str(identity['email']).strip()
        if '@' not in email:raise ValueError
        dob=parse_date(str(identity['date_of_birth']))
        if not dob or dob>timezone.localdate() or dob<date(1900,1,1):raise ValueError
        if data.get('consent_accepted') is not True:raise ValueError
        signature=str(data['signature'])
        _signature_bytes(signature)
    except (ValueError,KeyError,TypeError,UnicodeError,json.JSONDecodeError):
        return _json_error('invalid_intake')
    with transaction.atomic():
        existing=OfficeIntakeForm.objects.select_for_update().filter(source_id=source_id).first()
        if existing:
            return JsonResponse({'ok':True,'status':existing.status,
                'customer_id':existing.customer_id,'record_id':str(existing.record.public_id) if existing.record else None,
                'replayed':True})
        candidate,conflict=locate_unique_intake_patient(identity)
        if not candidate and not conflict:
            candidate=Customer.objects.create(
                first_name=str(identity['first_name']).strip()[:80],
                last_name=str(identity['last_name']).strip()[:80],
                email=email[:254],phone=str(identity['phone']).strip()[:40],
                date_of_birth=dob)
        if candidate and not candidate.date_of_birth:
            candidate.date_of_birth=dob
            candidate.save(update_fields=['date_of_birth','updated_at'])
        item=OfficeIntakeForm.objects.create(
            source_id=source_id,customer=candidate,payload={'identity':identity,'answers':answers,
                'consent_accepted':True,'consent_text':CONSENT_TEXT},
            signature_png=signature,status='linked' if candidate else 'review',
            match_count=match_score(identity,candidate) if candidate else 0)
        if candidate:
            attach_private_record(item)
    return JsonResponse({'ok':True,'status':item.status,'customer_id':item.customer_id,
        'record_id':str(item.record.public_id) if item.record else None,
        'requires_review':bool(conflict)}, status=201)

def confirm_form_link(form_id, customer_id, actor):
    with transaction.atomic():
        form=OfficeIntakeForm.objects.select_for_update().get(pk=form_id)
        if form.status=='linked':
            if form.customer_id!=customer_id:
                raise ValueError('Formular ist bereits einer anderen Akte zugeordnet.')
            return form
        customer=Customer.objects.get(pk=customer_id)
        count=match_score(form.payload.get('identity') or {},customer)
        if count<3:
            raise ValueError('Weniger als drei übereinstimmende Identitätsmerkmale.')
        form.customer=customer
        form.status='linked'
        form.match_count=count
        form.reviewed_by=actor
        form.reviewed_at=timezone.now()
        form.save(update_fields=['customer','status','match_count','reviewed_by','reviewed_at'])
        attach_private_record(form)
        return form
