from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0023_blockedbookingconflictalert'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientIdentityDecision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(
                    choices=[('approve', 'Zusammenführen bestätigen'),
                             ('reject', 'Nicht dieselbe Person'),
                             ('revoke', 'Verknüpfung aufheben')],
                    max_length=12,
                )),
                ('reason', models.CharField(max_length=120)),
                ('snapshot', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('left', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='identity_decisions_left', to='booking.customer')),
                ('right', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='identity_decisions_right', to='booking.customer')),
                ('primary_customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='identity_decisions_primary', to='booking.customer')),
                ('reviewed_by', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='patient_identity_decisions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Prüfung möglicher Patienten-Duplikate',
                'verbose_name_plural': 'Prüfungen möglicher Patienten-Duplikate',
                'ordering': ['-created_at', '-pk'],
                'indexes': [models.Index(fields=['left', 'right', '-id'], name='patient_decision_pair_idx')],
                'constraints': [models.CheckConstraint(
                    condition=models.Q(('left__lt', models.F('right'))),
                    name='patient_decision_ordered_pair',
                )],
            },
        ),
    ]
