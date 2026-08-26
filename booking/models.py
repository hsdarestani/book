import uuid
from django.core.exceptions import ValidationError
from django.db import models


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

    def __str__(self):
        return self.name


class StaffMember(models.Model):
    ROLE = [
        ('doctor', 'Arzt / Ärztin'),
        ('specialist', 'Behandler / Behandlerin'),
        ('team', 'Team'),
    ]
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

    def __str__(self):
        return self.display_name


class WorkingHour(models.Model):
    WEEKDAYS = [
        (0, 'Montag'), (1, 'Dienstag'), (2, 'Mittwoch'), (3, 'Donnerstag'),
        (4, 'Freitag'), (5, 'Samstag'), (6, 'Sonntag'),
    ]
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='working_hours', verbose_name='Mitarbeiter')
    weekday = models.PositiveSmallIntegerField('Wochentag', choices=WEEKDAYS)
    start_time = models.TimeField('Beginn')
    end_time = models.TimeField('Ende')
    active = models.BooleanField('Aktiv', default=True)

    class Meta:
        ordering = ['staff', 'weekday', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['staff', 'weekday', 'start_time'], name='unique_staff_working_hour_start')
        ]
        verbose_name = 'Arbeitszeit'
        verbose_name_plural = 'Arbeitszeiten'

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError('Das Ende muss nach dem Beginn liegen.')

    def __str__(self):
        return f'{self.staff} – {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}'


class BlockedPeriod(models.Model):
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name='blocked_periods', verbose_name='Mitarbeiter')
    starts_at = models.DateTimeField('Beginn')
    ends_at = models.DateTimeField('Ende')
    reason = models.CharField('Grund', max_length=160, blank=True)

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'Abwesenheit'
        verbose_name_plural = 'Abwesenheiten'

    def clean(self):
        if self.ends_at <= self.starts_at:
            raise ValidationError('Das Ende muss nach dem Beginn liegen.')

    def __str__(self):
        return f'{self.staff} – {self.starts_at:%d.%m.%Y %H:%M}'


class Customer(models.Model):
    first_name = models.CharField('Vorname', max_length=80)
    last_name = models.CharField('Nachname', max_length=80)
    phone = models.CharField('Telefon', max_length=40, blank=True)
    email = models.EmailField('E-Mail')
    created_at = models.DateTimeField('Erstellt am', auto_now_add=True)
    updated_at = models.DateTimeField('Aktualisiert am', auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        indexes = [models.Index(fields=['email'])]
        verbose_name = 'Kunde'
        verbose_name_plural = 'Kunden'

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def __str__(self):
        return self.full_name


class Appointment(models.Model):
    STATUS = [
        ('new', 'Neu'),
        ('confirmed', 'Bestätigt'),
        ('cancelled', 'Abgesagt'),
        ('completed', 'Abgeschlossen'),
        ('no_show', 'Nicht erschienen'),
    ]
    SOURCE = [('web', 'Webseite'), ('app', 'App'), ('admin', 'Verwaltung')]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='appointments', verbose_name='Kunde')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='appointments', verbose_name='Behandlung')
    staff = models.ForeignKey(StaffMember, on_delete=models.PROTECT, related_name='appointments', verbose_name='Mitarbeiter')
    starts_at = models.DateTimeField('Beginn')
    ends_at = models.DateTimeField('Ende')
    status = models.CharField('Status', max_length=20, choices=STATUS, default='new')
    source = models.CharField('Quelle', max_length=20, choices=SOURCE, default='web')
    notes_customer = models.TextField('Nachricht des Kunden', blank=True)
    idempotency_key = models.CharField(max_length=80, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField('Erstellt am', auto_now_add=True)
    updated_at = models.DateTimeField('Aktualisiert am', auto_now=True)

    class Meta:
        ordering = ['starts_at']
        indexes = [models.Index(fields=['starts_at', 'staff', 'status'])]
        verbose_name = 'Termin'
        verbose_name_plural = 'Termine'

    def clean(self):
        if self.ends_at <= self.starts_at:
            raise ValidationError('Das Ende muss nach dem Beginn liegen.')
        if self.staff_id and self.service_id and not self.staff.services.filter(pk=self.service_id).exists():
            raise ValidationError('Diese Behandlung ist diesem Mitarbeiter nicht zugeordnet.')
        if self.staff_id and self.status != 'cancelled':
            conflict = Appointment.objects.filter(
                staff=self.staff,
                status__in=['new', 'confirmed'],
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            ).exclude(pk=self.pk)
            if conflict.exists():
                raise ValidationError('Dieser Termin überschneidet sich mit einem bestehenden Termin.')

    def __str__(self):
        return f'{self.service} – {self.customer} – {self.starts_at:%d.%m.%Y %H:%M}'
