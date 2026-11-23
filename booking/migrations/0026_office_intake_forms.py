from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

def ensure_optional_birth_date(apps, schema_editor):
    """Production may already have this field from earlier manual/partial rollout.

    Preserve existing patient DOB values. On clean databases add the field.
    Migration state is the same in both cases, so later migrations remain valid.
    """
    patient = apps.get_model('booking', 'Customer')
    table = patient._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        existing = {column.name for column in
                    schema_editor.connection.introspection.get_table_description(cursor, table)}
    if 'date_of_birth' in existing:
        return
    field = models.DateField('Geburtsdatum', null=True, blank=True)
    field.set_attributes_from_name('date_of_birth')
    field.model = patient
    schema_editor.add_field(patient, field)


class Migration(migrations.Migration):
    dependencies = [('booking','0025_block_qamar_until_2027'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(
                ensure_optional_birth_date, reverse_code=migrations.RunPython.noop)],
            state_operations=[migrations.AddField(
                model_name='customer', name='date_of_birth',
                field=models.DateField('Geburtsdatum', blank=True, null=True))],
        ),
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
