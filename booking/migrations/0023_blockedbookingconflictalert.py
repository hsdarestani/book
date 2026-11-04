from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [('booking', '0022_admin_reminder_delivery_tracking')]

    operations = [
        migrations.CreateModel(
            name='BlockedBookingConflictAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('block_starts_at', models.DateTimeField()),
                ('block_ends_at', models.DateTimeField()),
                ('appointment_starts_at', models.DateTimeField()),
                ('source_note_id', models.CharField(blank=True, max_length=80)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('push_sent_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('appointment', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='block_conflict_alerts', to='booking.appointment')),
                ('blocked_period', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='booking_conflict_alerts', to='booking.blockedperiod')),
            ],
            options={
                'verbose_name': 'Terminkonflikt mit SimplyBook-Sperre',
                'verbose_name_plural': 'Terminkonflikte mit SimplyBook-Sperren',
                'ordering': ['created_at', 'pk'],
            },
        ),
    ]
