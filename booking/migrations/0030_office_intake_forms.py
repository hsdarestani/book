from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('booking','0029_native_identity_review_actor'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='OfficeIntakeForm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_id', models.UUIDField(editable=False, unique=True)),
                ('payload', models.JSONField(default=dict)),
                ('signature_png', models.TextField(blank=True)),
                ('consent_version', models.CharField(default='intake-2026-11', max_length=40)),
                ('status', models.CharField(choices=[('linked','Zugeordnet'),('review','Prüfung nötig')], db_index=True, default='review', max_length=10)),
                ('match_count', models.PositiveSmallIntegerField(default=0)),
                ('submitted_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('customer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='office_intake_forms', to='booking.customer')),
                ('record', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='office_intake_form', to='booking.patientrecord')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_office_forms', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-submitted_at'],'verbose_name':'Aufnahmebogen','verbose_name_plural':'Aufnahmebögen'},
        ),
    ]
