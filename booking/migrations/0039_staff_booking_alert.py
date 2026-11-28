from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies = [('booking', '0038_staff_patient_contact')]
    operations = [
        migrations.CreateModel(
            name='StaffBookingAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('push_sent_at', models.DateTimeField(blank=True, null=True)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('appointment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='staff_booking_alert', to='booking.appointment')),
            ],
        ),
    ]
