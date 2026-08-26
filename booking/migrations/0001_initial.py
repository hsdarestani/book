# Generated for the initial A+esthetic Booking schema.
import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='Customer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=80, verbose_name='Vorname')),
                ('last_name', models.CharField(max_length=80, verbose_name='Nachname')),
                ('phone', models.CharField(blank=True, max_length=40, verbose_name='Telefon')),
                ('email', models.EmailField(max_length=254, verbose_name='E-Mail')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Erstellt am')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Aktualisiert am')),
            ],
            options={'verbose_name': 'Kunde', 'verbose_name_plural': 'Kunden', 'ordering': ['last_name', 'first_name']},
        ),
        migrations.CreateModel(
            name='Service',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=140, verbose_name='Bezeichnung')),
                ('slug', models.SlugField(unique=True)),
                ('description', models.TextField(blank=True, verbose_name='Beschreibung')),
                ('duration_minutes', models.PositiveIntegerField(default=30, verbose_name='Dauer in Minuten')),
                ('buffer_minutes', models.PositiveIntegerField(default=10, verbose_name='Puffer in Minuten')),
                ('price_label', models.CharField(blank=True, max_length=80, verbose_name='Preisangabe')),
                ('active', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('bookable', models.BooleanField(default=True, verbose_name='Online buchbar')),
                ('requires_confirmation', models.BooleanField(default=False, verbose_name='Manuelle Bestätigung erforderlich')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='Reihenfolge')),
            ],
            options={'verbose_name': 'Behandlung', 'verbose_name_plural': 'Behandlungen', 'ordering': ['sort_order', 'name']},
        ),
        migrations.CreateModel(
            name='StaffMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('display_name', models.CharField(max_length=120, verbose_name='Name')),
                ('role', models.CharField(choices=[('doctor', 'Arzt / Ärztin'), ('specialist', 'Behandler / Behandlerin'), ('team', 'Team')], default='specialist', max_length=20, verbose_name='Rolle')),
                ('bio', models.TextField(blank=True, verbose_name='Kurzbeschreibung')),
                ('photo', models.ImageField(blank=True, upload_to='staff/', verbose_name='Profilbild')),
                ('active', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='Reihenfolge')),
                ('services', models.ManyToManyField(blank=True, related_name='staff_members', to='booking.service', verbose_name='Behandlungen')),
            ],
            options={'verbose_name': 'Mitarbeiter', 'verbose_name_plural': 'Mitarbeiter', 'ordering': ['sort_order', 'display_name']},
        ),
        migrations.CreateModel(
            name='WorkingHour',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weekday', models.PositiveSmallIntegerField(choices=[(0, 'Montag'), (1, 'Dienstag'), (2, 'Mittwoch'), (3, 'Donnerstag'), (4, 'Freitag'), (5, 'Samstag'), (6, 'Sonntag')], verbose_name='Wochentag')),
                ('start_time', models.TimeField(verbose_name='Beginn')),
                ('end_time', models.TimeField(verbose_name='Ende')),
                ('active', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='working_hours', to='booking.staffmember', verbose_name='Mitarbeiter')),
            ],
            options={'verbose_name': 'Arbeitszeit', 'verbose_name_plural': 'Arbeitszeiten', 'ordering': ['staff', 'weekday', 'start_time']},
        ),
        migrations.CreateModel(
            name='BlockedPeriod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('starts_at', models.DateTimeField(verbose_name='Beginn')),
                ('ends_at', models.DateTimeField(verbose_name='Ende')),
                ('reason', models.CharField(blank=True, max_length=160, verbose_name='Grund')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocked_periods', to='booking.staffmember', verbose_name='Mitarbeiter')),
            ],
            options={'verbose_name': 'Abwesenheit', 'verbose_name_plural': 'Abwesenheiten', 'ordering': ['starts_at']},
        ),
        migrations.CreateModel(
            name='Appointment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('starts_at', models.DateTimeField(verbose_name='Beginn')),
                ('ends_at', models.DateTimeField(verbose_name='Ende')),
                ('status', models.CharField(choices=[('new', 'Neu'), ('confirmed', 'Bestätigt'), ('cancelled', 'Abgesagt'), ('completed', 'Abgeschlossen'), ('no_show', 'Nicht erschienen')], default='new', max_length=20, verbose_name='Status')),
                ('source', models.CharField(choices=[('web', 'Webseite'), ('app', 'App'), ('admin', 'Verwaltung')], default='web', max_length=20, verbose_name='Quelle')),
                ('notes_customer', models.TextField(blank=True, verbose_name='Nachricht des Kunden')),
                ('idempotency_key', models.CharField(blank=True, editable=False, max_length=80, null=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Erstellt am')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Aktualisiert am')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appointments', to='booking.customer', verbose_name='Kunde')),
                ('service', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appointments', to='booking.service', verbose_name='Behandlung')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='appointments', to='booking.staffmember', verbose_name='Mitarbeiter')),
            ],
            options={'verbose_name': 'Termin', 'verbose_name_plural': 'Termine', 'ordering': ['starts_at']},
        ),
        migrations.AddIndex(model_name='customer', index=models.Index(fields=['email'], name='booking_cus_email_4d5e77_idx')),
        migrations.AddConstraint(model_name='workinghour', constraint=models.UniqueConstraint(fields=('staff', 'weekday', 'start_time'), name='unique_staff_working_hour_start')),
        migrations.AddIndex(model_name='appointment', index=models.Index(fields=['starts_at', 'staff', 'status'], name='booking_app_starts__1de48f_idx')),
    ]
