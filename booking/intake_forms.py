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

from .internal_api import _authorized, _patient_path, _store_bytes
from .intake_identity import identity_values, locate_unique_intake_patient, match_score
from .models import Customer, OfficeIntakeAssignmentLock, OfficeIntakeForm, PatientRecord

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
    for line in (data.get('consent_text') or CONSENT_TEXT).split('\n'):
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
    try:
        record=PatientRecord.objects.create(
            customer=form.customer, kind='form', title='Allgemeiner Aufnahmebogen',
            note='Vom Patienten digital ausgefüllter Aufnahmebogen und Unterschrift.',
            stored_name=stored,original_name=original,mime_type=mime,file_size=size,
            source='office_intake',external_id=str(form.source_id),
            captured_at=form.submitted_at,metadata={'form_id':form.pk,'shared_with_customer':False})
        form.record=record
        form.save(update_fields=['record'])
    except Exception:
        # A failed database write must not leave our newly generated private file.
        _patient_path(stored).unlink(missing_ok=True)
        raise


def _lock_assignment():
    # Serialize patient creation and form assignment, including historical forms.
    if not OfficeIntakeAssignmentLock.objects.filter(pk=1).update(id=1):
        raise RuntimeError('Office intake assignment lock is missing')


def _complete_identity(identity):
    return all(identity_values(identity)) and all(
        isinstance(identity.get(field), str) and len(identity[field].strip()) <= limit
        for field, limit in {'first_name':80, 'last_name':80, 'email':254, 'phone':40}.items()
    )


def _create_intake_patient(identity):
    return Customer.objects.create(
        first_name=identity['first_name'].strip(), last_name=identity['last_name'].strip(),
        email=identity['email'].strip(), phone=identity['phone'].strip(),
        date_of_birth=parse_date(str(identity['date_of_birth'])))


def _compatible_existing_record(form, candidate):
    record=form.record if form.record_id else PatientRecord.objects.filter(
        source='office_intake', external_id=str(form.source_id)).first()
    if record and (not candidate or record.customer_id != candidate.pk or record.kind != 'form'
            or record.source != 'office_intake' or record.external_id != str(form.source_id)
            or not record.has_file
            or OfficeIntakeForm.objects.filter(record_id=record.pk).exclude(pk=form.pk).exists()):
        raise ValueError('Aufnahmebogen hat eine abweichende oder unvollständige verknüpfte Datei.')
    return record


def _historical_assignment(form, *, apply):
    """Reconcile an unassigned signed form without altering its content or past audit.

    Return a fixed aggregate-only outcome. Never create from incomplete identity or
    overwrite a pre-existing record for another patient.
    """
    if form.status != 'review' or form.customer_id:
        return 'already_resolved'
    payload=form.payload
    identity=payload.get('identity') if isinstance(payload, dict) else None
    if (not isinstance(identity, dict) or payload.get('consent_accepted') is not True
            or not isinstance(payload.get('answers'), dict)
            or not isinstance(payload.get('consent_text'), str) or not payload['consent_text'].strip()):
        return 'review_invalid_signed_form'
    try:
        _signature_bytes(form.signature_png)
    except ValueError:
        return 'review_invalid_signed_form'
    candidate,conflict=locate_unique_intake_patient(identity)
    if conflict:
        return 'review_identity_conflict'
    try:
        record=_compatible_existing_record(form,candidate)
    except ValueError:
        return 'review_record_conflict'
    if not candidate and not _complete_identity(identity):
        return 'review_missing_identity'
    outcome='matched' if candidate else 'created'
    if not apply:
        return outcome
    if not candidate:
        candidate=_create_intake_patient(identity)
    form.customer=candidate
    form.status='linked'
    form.match_count=match_score(identity,candidate)
    form.record=record
    # The signed payload, source id, signature and any previous review audit stay unchanged.
    if not form.reviewed_at:
        form.reviewed_at=timezone.now()
    form.save(update_fields=['customer','status','match_count','record','reviewed_at'])
    if not record:
        attach_private_record(form)
    return outcome


def reconcile_unassigned_form(form_id, *, apply=False):
    if not apply:
        form=OfficeIntakeForm.objects.filter(pk=form_id).first()
        return _historical_assignment(form, apply=False) if form else 'already_resolved'
    with transaction.atomic():
        _lock_assignment()
        form=OfficeIntakeForm.objects.select_for_update().filter(pk=form_id).first()
        return _historical_assignment(form, apply=True) if form else 'already_resolved'

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
        if not _complete_identity(identity):
            raise ValueError
        dob=parse_date(str(identity['date_of_birth']))
        if not dob or dob>timezone.localdate() or dob<date(1900,1,1):raise ValueError
        if data.get('consent_accepted') is not True:raise ValueError
        signature=str(data['signature'])
        _signature_bytes(signature)
    except (ValueError,KeyError,TypeError,UnicodeError,json.JSONDecodeError):
        return _json_error('invalid_intake')
    with transaction.atomic():
        # Take the write lock as the first statement. A second request will
        # see the first patient's committed identity before resolving its own.
        _lock_assignment()
        existing=OfficeIntakeForm.objects.select_for_update().filter(source_id=source_id).first()
        if existing:
            if (existing.payload.get('identity') != identity
                    or existing.payload.get('answers') != answers
                    or existing.signature_png != signature):
                return _json_error('source_id_payload_mismatch', 409)
            if existing.status == 'review' and not existing.customer_id:
                _historical_assignment(existing, apply=True)
            return JsonResponse({'ok':True,'status':existing.status,
                'customer_id':existing.customer_id,'record_id':str(existing.record.public_id) if existing.record else None,
                'replayed':True})
        candidate,conflict=locate_unique_intake_patient(identity)
        if not candidate and not conflict:
            candidate=_create_intake_patient(identity)
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
        _lock_assignment()
        form=OfficeIntakeForm.objects.select_for_update().get(pk=form_id)
        if form.status=='linked':
            if form.customer_id!=customer_id:
                raise ValueError('Formular ist bereits einer anderen Akte zugeordnet.')
            return form
        customer=Customer.objects.get(pk=customer_id)
        count=match_score(form.payload.get('identity') or {},customer)
        if count<3:
            raise ValueError('Weniger als drei übereinstimmende Identitätsmerkmale.')
        record=_compatible_existing_record(form, customer)
        form.customer=customer
        form.status='linked'
        form.match_count=count
        form.record=record
        form.reviewed_by=actor
        form.reviewed_at=timezone.now()
        form.save(update_fields=['customer','status','match_count','record','reviewed_by','reviewed_at'])
        attach_private_record(form)
        return form
