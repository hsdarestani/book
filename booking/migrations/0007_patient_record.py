import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0006_correct_brand_spelling'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('kind', models.CharField(choices=[('photo', 'Foto'), ('form', 'Formular'), ('document', 'Dokument'), ('note', 'Notiz'), ('other', 'Sonstiges')], default='document', max_length=20, verbose_name='Typ')),
                ('title', models.CharField(max_length=180, verbose_name='Titel')),
                ('note', models.TextField(blank=True, verbose_name='Notiz')),
                ('stored_name', models.CharField(blank=True, editable=False, max_length=180, verbose_name='Interner Dateiname')),
                ('original_name', models.CharField(blank=True, editable=False, max_length=255, verbose_name='Originaldatei')),
                ('mime_type', models.CharField(blank=True, editable=False, max_length=120, verbose_name='Dateityp')),
                ('file_size', models.PositiveBigIntegerField(default=0, editable=False, verbose_name='Dateigröße')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Erstellt am')),
                ('appointment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='patient_records', to='booking.appointment', verbose_name='Termin')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='patient_records', to='booking.customer', verbose_name='Patient')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='patient_records_uploaded', to=settings.AUTH_USER_MODEL, verbose_name='Hochgeladen von')),
            ],
            options={
                'verbose_name': 'Patientenakte-Eintrag',
                'verbose_name_plural': 'Patientenakte-Einträge',
                'ordering': ['-created_at', '-pk'],
            },
        ),
        migrations.AddIndex(
            model_name='patientrecord',
            index=models.Index(fields=['customer', '-created_at'], name='patient_record_customer_idx'),
        ),
    ]
