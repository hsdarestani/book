from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0009_first_consultation_price'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyAvailabilityOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(verbose_name='Datum')),
                ('closed', models.BooleanField(default=False, verbose_name='Ganztägig nicht verfügbar')),
                ('start_time_1', models.TimeField(blank=True, null=True, verbose_name='Beginn 1')),
                ('end_time_1', models.TimeField(blank=True, null=True, verbose_name='Ende 1')),
                ('start_time_2', models.TimeField(blank=True, null=True, verbose_name='Beginn 2')),
                ('end_time_2', models.TimeField(blank=True, null=True, verbose_name='Ende 2')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_availability_overrides', to='booking.staffmember', verbose_name='Mitarbeiter')),
            ],
            options={
                'verbose_name': 'Tages-Verfügbarkeit',
                'verbose_name_plural': 'Tages-Verfügbarkeiten',
                'ordering': ['date', 'staff'],
            },
        ),
        migrations.AddConstraint(
            model_name='dailyavailabilityoverride',
            constraint=models.UniqueConstraint(fields=('staff', 'date'), name='unique_staff_daily_availability'),
        ),
    ]
