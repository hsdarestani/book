from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [('booking', '0007_patient_record')]

    operations = [
        migrations.AddField(
            model_name='patientrecord',
            name='source',
            field=models.CharField(db_index=True, default='manual', max_length=60, verbose_name='Quelle'),
        ),
        migrations.AddField(
            model_name='patientrecord',
            name='external_id',
            field=models.CharField(blank=True, max_length=180, verbose_name='Externe Referenz'),
        ),
        migrations.AddField(
            model_name='patientrecord',
            name='captured_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Erfasst am'),
        ),
        migrations.AddField(
            model_name='patientrecord',
            name='metadata',
            field=models.JSONField(blank=True, default=dict, verbose_name='Metadaten'),
        ),
        migrations.AddConstraint(
            model_name='patientrecord',
            constraint=models.UniqueConstraint(
                fields=('source', 'external_id'),
                condition=~Q(external_id=''),
                name='unique_patient_record_external_source',
            ),
        ),
    ]
