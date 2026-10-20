from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0018_externalsyncstate'),
    ]

    operations = [
        migrations.CreateModel(
            name='DoctorPatientAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='doctor_access', to='booking.customer')),
                ('staff', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='doctor_patient_access', to='booking.staffmember')),
            ],
        ),
        migrations.AddConstraint(
            model_name='doctorpatientaccess',
            constraint=models.UniqueConstraint(fields=('staff', 'customer'), name='unique_doctor_patient_access'),
        ),
    ]
