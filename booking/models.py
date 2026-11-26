import uuid
from datetime import UTC, timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .clinical_time import add_elapsed


class Service(models.Model):
    name = models.CharField('Bezeichnung', max_length=140)
    slug = models.SlugField(unique=True)
    description = models.TextField('Beschreibung', blank=True)
    duration_minutes = models.PositiveIntegerField('Dauer in Minuten', default=30)
    buffer_minutes = models.PositiveIntegerField('Puffer in Minuten', default=10)
    price_label = models.CharField('Preisangabe', max_length=80, blank=True)
    active = models.BooleanField('Aktiv', default=True)
    bookable = models.BooleanField('Online buchbar', default=True)
    requires_confirmation = models.BooleanField('Manuelle Bestätigung erforderlich', default=False)
    sort_order = models.PositiveIntegerField('Reihenfolge', default=100)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = 'Behandlung'
        verbose_name_plural = 'Behandlungen'

    @property
    def reserved_duration(self):
        return timedelta(minutes=self.duration_minutes + self.buffer_minutes)

    def __str__(self): return self.name


class StaffMember(models.Model):
    ROLE = [('doctor', 'Arzt / Ärztin'), ('specialist', 'Behandler / Behandlerin'), ('team', 'Team')]
    display_name = models.CharField('Name', max_length=120)
    role = models.CharField('Rolle', max_length=20, choices=ROLE, default='specialist')
    bio = models.TextField('Kurzbeschreibung', blank=True)
    photo = models.ImageField('Profilbild', upload_to='staff/', blank=True)
    services = models.ManyToManyField(Service, verbose_name='Behandlungen', blank=True, related_name='staff_members')
    active = models.BooleanField('Aktiv', default=True)
    sort_order = models.PositiveIntegerField('Reihenfolge', default=100)

    class Meta:
        ordering = ['sort_order', 'display_name']
        verbose_name = 'Mitarbeiter'
        verbose_name_plural = 'Mitarbeiter'

    def __str__(self): return self.display_name


class WorkingHour(models.Model):
    WEEKDAYS = [(0,'Montag'),(1,'Dienstag'),(2,'Mittwoch'),(3,'Donnerstag'),(4,'Freitag'),(5,'Samstag'),(6,'Sonntag')]
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='working_hours', verbose_name='Mitarbeiter')
    weekday = models.PositiveSmallIntegerField('Wochentag', choices=WEEKDAYS)
    start_time = models.TimeField('Beginn')
    end_time = models.TimeField('Ende')
    active = models.BooleanField('Aktiv', default=True)

    class Meta:
        ordering = ['staff', 'weekday', 'start_time']
        constraints = [models.UniqueConstraint(fields=['staff','weekday','start_time'], name='unique_staff_working_hour_start')]
        verbose_name = 'Arbeitszeit'; verbose_name_plural = 'Arbeitszeiten'

    def clean(self):
        if self.end_time <= self.start_time: raise ValidationError('Das Ende muss nach dem Beginn liegen.')
    def __str__(self): return f'{self.staff} – {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}'


class DailyAvailabilityOverride(models.Model):
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='daily_availability_overrides', verbose_name='Mitarbeiter')
    date = models.DateField('Datum')
    closed = models.BooleanField('Ganztägig nicht verfügbar', default=False)
    start_time_1 = models.TimeField('Beginn 1', null=True, blank=True)
    end_time_1 = models.TimeField('Ende 1', null=True, blank=True)
    start_time_2 = models.TimeField('Beginn 2', null=True, blank=True)
    end_time_2 = models.TimeField('Ende 2', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date','staff']
        constraints = [models.UniqueConstraint(fields=['staff','date'], name='unique_staff_daily_availability')]
        verbose_name = 'Tages-Verfügbarkeit'; verbose_name_plural = 'Tages-Verfügbarkeiten'

    def clean(self):
        if self.closed: return
        if not self.start_time_1 or not self.end_time_1: raise ValidationError('Für einen offenen Tag muss mindestens ein Zeitraum angegeben werden.')
        if self.end_time_1 <= self.start_time_1: raise ValidationError('Das Ende des ersten Zeitraums muss nach dem Beginn liegen.')
        has_second = bool(self.start_time_2 or self.end_time_2)
        if has_second and not (self.start_time_2 and self.end_time_2): raise ValidationError('Der zweite Zeitraum muss vollständig angegeben werden.')
        if self.start_time_2 and self.end_time_2:
            if self.end_time_2 <= self.start_time_2: raise ValidationError('Das Ende des zweiten Zeitraums muss nach dem Beginn liegen.')
            if self.start_time_2 < self.end_time_1: raise ValidationError('Die Tages-Zeiträume dürfen sich nicht überschneiden.')

    def ranges(self):
        if self.closed: return []
        result=[]
        if self.start_time_1 and self.end_time_1: result.append((self.start_time_1,self.end_time_1))
        if self.start_time_2 and self.end_time_2: result.append((self.start_time_2,self.end_time_2))
        return result
    def __str__(self): return f'{self.staff} – {self.date:%d.%m.%Y}'


class BlockedPeriod(models.Model):
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='blocked_periods', verbose_name='Mitarbeiter')
    starts_at = models.DateTimeField('Beginn')
    ends_at = models.DateTimeField('Ende')
    reason = models.CharField('Grund', max_length=160, blank=True)
    class Meta:
        ordering=['starts_at']; verbose_name='Abwesenheit'; verbose_name_plural='Abwesenheiten'
    def clean(self):
        if self.ends_at <= self.starts_at: raise ValidationError('Das Ende muss nach dem Beginn liegen.')
    def __str__(self): return f'{self.staff} – {self.starts_at:%d.%m.%Y %H:%M}'


class Customer(models.Model):
    SALUTATION = [('', 'Neutral / nicht angegeben'), ('frau', 'Frau'), ('herr', 'Herr'), ('divers', 'Divers')]
    first_name = models.CharField('Vorname', max_length=80)
    last_name = models.CharField('Nachname', max_length=80)
    salutation = models.CharField('Anrede', max_length=10, choices=SALUTATION, blank=True, default='')
    phone = models.CharField('Telefon', max_length=40, blank=True)
    email = models.EmailField('E-Mail')
    date_of_birth = models.DateField('Geburtsdatum', null=True, blank=True)
    created_at = models.DateTimeField('Erstellt am', auto_now_add=True)
    updated_at = models.DateTimeField('Aktualisiert am', auto_now=True)

    class Meta:
        ordering=['last_name','first_name']
        indexes=[models.Index(fields=['email'], name='booking_cus_email_4d5e77_idx')]
        verbose_name='Kunde'; verbose_name_plural='Kunden'

    @property
    def full_name(self): return f'{self.first_name} {self.last_name}'.strip()
    def __str__(self): return self.full_name


class PatientRecord(models.Model):
    KIND=[('photo','Foto'),('form','Formular'),('document','Dokument'),('note','Notiz'),('other','Sonstiges')]
    public_id=models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer=models.ForeignKey(Customer,on_delete=models.CASCADE,related_name='patient_records',verbose_name='Patient')
    appointment=models.ForeignKey('Appointment',on_delete=models.SET_NULL,related_name='patient_records',null=True,blank=True,verbose_name='Termin')
    kind=models.CharField('Typ',max_length=20,choices=KIND,default='document')
    title=models.CharField('Titel',max_length=180)
    note=models.TextField('Notiz',blank=True)
    stored_name=models.CharField('Interner Dateiname',max_length=180,blank=True,editable=False)
    original_name=models.CharField('Originaldatei',max_length=255,blank=True,editable=False)
    mime_type=models.CharField('Dateityp',max_length=120,blank=True,editable=False)
    file_size=models.PositiveBigIntegerField('Dateigröße',default=0,editable=False)
    source=models.CharField('Quelle',max_length=60,default='manual',db_index=True)
    external_id=models.CharField('Externe Referenz',max_length=180,blank=True)
    captured_at=models.DateTimeField('Erfasst am',null=True,blank=True)
    metadata=models.JSONField('Metadaten',default=dict,blank=True)
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name='patient_records_uploaded',verbose_name='Hochgeladen von')
    created_at=models.DateTimeField('Erstellt am',auto_now_add=True)
    class Meta:
        ordering=['-created_at','-pk']; verbose_name='Patientenakte-Eintrag'; verbose_name_plural='Patientenakte-Einträge'
        indexes=[models.Index(fields=['customer','-created_at'],name='patient_record_customer_idx')]
        constraints=[models.UniqueConstraint(fields=['source','external_id'],condition=~Q(external_id=''),name='unique_patient_record_external_source')]
    @property
    def has_file(self): return bool(self.stored_name)
    @property
    def is_image(self): return self.mime_type.startswith('image/') if self.mime_type else False
    def __str__(self): return f'{self.customer} – {self.title}'


class OfficeIntakeForm(models.Model):
    """Private general Aufnahmebogen; never exposed by the patient portal."""
    STATUS = [('linked','Zugeordnet'),('review','Prüfung nötig')]
    source_id = models.UUIDField(unique=True, editable=False)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name='office_intake_forms')
    record = models.OneToOneField(PatientRecord, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='office_intake_form')
    payload = models.JSONField(default=dict)
    signature_png = models.TextField(blank=True)
    consent_version = models.CharField(max_length=40, default='intake-2026-11')
    status = models.CharField(max_length=10, choices=STATUS, default='review', db_index=True)
    match_count = models.PositiveSmallIntegerField(default=0)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='reviewed_office_forms')
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-submitted_at']
        verbose_name = 'Aufnahmebogen'
        verbose_name_plural = 'Aufnahmebögen'


class Appointment(models.Model):
    STATUS=[('new','Neu'),('confirmed','Bestätigt'),('cancelled','Abgesagt'),('completed','Abgeschlossen'),('no_show','Nicht erschienen')]
    SOURCE=[('web','Webseite'),('app','App'),('admin','Verwaltung')]
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='appointments',verbose_name='Kunde')
    service=models.ForeignKey(Service,on_delete=models.PROTECT,related_name='appointments',verbose_name='Behandlung')
    staff=models.ForeignKey(StaffMember,on_delete=models.PROTECT,related_name='appointments',verbose_name='Mitarbeiter')
    starts_at=models.DateTimeField('Beginn')
    ends_at=models.DateTimeField('Ende')
    treatment_minutes_at_booking = models.PositiveIntegerField(null=True, blank=True, editable=False)
    status=models.CharField('Status',max_length=20,choices=STATUS,default='new')
    source=models.CharField('Quelle',max_length=20,choices=SOURCE,default='web')
    notes_customer=models.TextField('Nachricht des Kunden',blank=True)
    returning_customer=models.BooleanField('Schon einmal bei uns',default=False)
    referral_source=models.CharField('Wie auf uns aufmerksam geworden',max_length=100,blank=True)
    marketing_opt_in=models.BooleanField('Marketing-Einwilligung',default=True)
    cancellation_terms_accepted=models.BooleanField('Stornierungsbedingungen akzeptiert',default=False)
    privacy_accepted=models.BooleanField('Datenschutz bestätigt',default=False)
    idempotency_key=models.CharField(max_length=80,unique=True,null=True,blank=True,editable=False)
    simplybook_booking_id=models.CharField(max_length=80,unique=True,null=True,blank=True,editable=False)
    simplybook_sync_state=models.CharField(max_length=20,blank=True,default='',editable=False)
    simplybook_event_id=models.CharField(max_length=80,blank=True,default='',editable=False)
    simplybook_client_id=models.CharField(max_length=80,blank=True,default='',editable=False)
    reminder_24h_sent_at=models.DateTimeField('24h-Erinnerung gesendet',null=True,blank=True,editable=False)
    reminder_1h_sent_at=models.DateTimeField('1h-Erinnerung gesendet',null=True,blank=True,editable=False)
    reminder_1h_admin_email_sent_at=models.DateTimeField('1h-Admin-Erinnerung E-Mail gesendet',null=True,blank=True,editable=False)
    reminder_1h_admin_push_sent_at=models.DateTimeField('1h-Admin-Erinnerung Push gesendet',null=True,blank=True,editable=False)
    created_at=models.DateTimeField('Erstellt am',auto_now_add=True)
    updated_at=models.DateTimeField('Aktualisiert am',auto_now=True)
    class Meta:
        ordering=['starts_at']; indexes=[models.Index(fields=['starts_at','staff','status'],name='booking_app_starts__1de48f_idx')]; verbose_name='Termin'; verbose_name_plural='Termine'
    @property
    def reserved_duration(self):
        return self.ends_at.astimezone(UTC) - self.starts_at.astimezone(UTC)

    def reservation_for(self, service):
        return self.reserved_duration if service.pk == self.service_id else service.reserved_duration

    @property
    def calendar_buffer_minutes(self):
        if self.treatment_minutes_at_booking is not None:
            buffer = self.reserved_duration - timedelta(minutes=self.treatment_minutes_at_booking)
            return max(0, int(buffer.total_seconds() // 60))
        # Keep the existing display for legacy local records where the stored
        # reservation agrees with the catalog. Imported spans remain opaque.
        if (self.idempotency_key or '').startswith('simplybook-') or not self.service_id:
            return 0
        if self.service.duration_minutes and self.reserved_duration == self.service.reserved_duration:
            return self.service.buffer_minutes
        return 0

    @property
    def calendar_treatment_end(self):
        return add_elapsed(self.ends_at, -timedelta(minutes=self.calendar_buffer_minutes))

    @property
    def calendar_buffer_percent(self):
        total = self.reserved_duration.total_seconds() / 60
        return round(100 * self.calendar_buffer_minutes / total) if total > 0 else 0

    def clean(self):
        if self.ends_at <= self.starts_at: raise ValidationError('Das Ende muss nach dem Beginn liegen.')
        if self.staff_id and self.service_id and not self.staff.services.filter(pk=self.service_id).exists(): raise ValidationError('Diese Behandlung ist diesem Mitarbeiter nicht zugeordnet.')
        if self.staff_id and self.status != 'cancelled':
            conflict=Appointment.objects.filter(staff=self.staff,status__in=['new','confirmed'],starts_at__lt=self.ends_at,ends_at__gt=self.starts_at).exclude(pk=self.pk)
            if conflict.exists(): raise ValidationError('Dieser Termin überschneidet sich mit einem bestehenden Termin.')
    def __str__(self): return f'{self.service} – {self.customer} – {self.starts_at:%d.%m.%Y %H:%M}'


class BlockedBookingConflictAlert(models.Model):
    """One audit record for a newly synchronized block overlapping a live booking.

    A changed or re-enabled block creates a new alert event. Delivery channel
    timestamps are independent, so a failed email/push can be retried safely.
    """
    appointment = models.ForeignKey(
        Appointment, on_delete=models.CASCADE, related_name='block_conflict_alerts',
    )
    blocked_period = models.ForeignKey(
        BlockedPeriod, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='booking_conflict_alerts',
    )
    block_starts_at = models.DateTimeField()
    block_ends_at = models.DateTimeField()
    appointment_starts_at = models.DateTimeField()
    source_note_id = models.CharField(max_length=80, blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    push_sent_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']
        verbose_name = 'Terminkonflikt mit SimplyBook-Sperre'
        verbose_name_plural = 'Terminkonflikte mit SimplyBook-Sperren'



class AdminAccessProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='aesthetic_access')
    staff = models.ForeignKey(StaffMember, null=True, blank=True, on_delete=models.SET_NULL, related_name='admin_access_profiles')
    view_only = models.BooleanField('Nur ansehen', default=False)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return f'{self.user} – {"View only" if self.view_only else "Bearbeiten"}'


class DoctorPatientAccess(models.Model):
    """Patients manually created/claimed by one clinician, independently of a booking."""
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='doctor_patient_access')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='doctor_access')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['staff', 'customer'], name='unique_doctor_patient_access')
        ]



class PatientIdentityDecision(models.Model):
    """Append-only, audited human decision to link or unlink two patient profiles.

    Links are logical: neither Customer nor the medical records, appointment
    ownership or external SimplyBook source IDs are rewritten or deleted.
    """
    ACTIONS = [
        ('approve', 'Zusammenführen bestätigen'),
        ('reject', 'Nicht dieselbe Person'),
        ('revoke', 'Verknüpfung aufheben'),
    ]
    left = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='identity_decisions_left')
    right = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='identity_decisions_right')
    primary_customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='identity_decisions_primary',
    )
    action = models.CharField(max_length=12, choices=ACTIONS)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='patient_identity_decisions',
        null=True, blank=True,
    )
    reviewed_by_aesthetic_id = models.PositiveBigIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=120)
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['left', 'right', '-id'], name='patient_decision_pair_idx')]
        constraints = [
            models.CheckConstraint(
                condition=Q(left__lt=models.F('right')),
                name='patient_decision_ordered_pair',
            ),
            models.CheckConstraint(
                condition=(Q(reviewed_by__isnull=False, reviewed_by_aesthetic_id__isnull=True) |
                           Q(reviewed_by__isnull=True, reviewed_by_aesthetic_id__isnull=False)),
                name='patient_decision_verified_actor',
            ),
        ]
        verbose_name = 'Prüfung möglicher Patienten-Duplikate'
        verbose_name_plural = 'Prüfungen möglicher Patienten-Duplikate'



class ExternalSyncState(models.Model):
    source = models.CharField(max_length=40, unique=True)
    baseline_completed_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Externer Sync-Status'
        verbose_name_plural = 'Externe Sync-Status'

    def __str__(self):
        return self.source


class WhatsAppTemplate(models.Model):
    name = models.CharField('Name', max_length=100)
    body = models.TextField('Text', help_text='Variablen: {anrede}, {vorname}, {nachname}, {name}')
    active = models.BooleanField('Aktiv', default=True)
    sort_order = models.PositiveIntegerField('Reihenfolge', default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['sort_order','name']; verbose_name='WhatsApp-Vorlage'; verbose_name_plural='WhatsApp-Vorlagen'
    def __str__(self): return self.name

    def render_for(self, customer):
        salutation = {'frau': 'Frau', 'herr': 'Herr', 'divers': 'Divers'}.get(customer.salutation, '')
        values = {'anrede': salutation, 'vorname': customer.first_name, 'nachname': customer.last_name, 'name': customer.full_name}
        text = self.body
        for key, value in values.items(): text = text.replace('{' + key + '}', value)
        return ' '.join(text.split())



class SimplyBookClientLink(models.Model):
    """Stable source-client identity without trusting shared emails/phone numbers.

    Several independent SimplyBook clients can share one contact address. The
    source client ID, not an email or phone, is the canonical sync identity.
    """
    external_client_id = models.CharField(max_length=80, unique=True)
    source_name = models.CharField(max_length=160, blank=True, default='')
    source_email = models.CharField(max_length=254, blank=True, default='')
    source_phone = models.CharField(max_length=40, blank=True, default='')
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='simplybook_client_links',
    )

    class Meta:
        verbose_name = 'SimplyBook-Kundenverknüpfung'
        verbose_name_plural = 'SimplyBook-Kundenverknüpfungen'


class MobileStaffCommand(models.Model):
    """Audit and replay receipt for commands issued by the bundled app."""
    actor_id = models.PositiveBigIntegerField()
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    action = models.CharField(max_length=32)
    object_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor_id', 'key'], name='mobile_staff_command_actor_key')]


class MobileStaffCancellation(models.Model):
    """Durable delivery of an idempotent package release after Book commits."""
    appointment = models.OneToOneField(
        Appointment, null=True, on_delete=models.SET_NULL, related_name='mobile_cancellation',
    )
    booking_public_id = models.UUIDField(unique=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True)
