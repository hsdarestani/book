from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0028_customer_date_of_birth'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AlterField(
            model_name='patientidentitydecision',
            name='reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='patient_identity_decisions', to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='patientidentitydecision', name='reviewed_by_aesthetic_id',
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='patientidentitydecision',
            constraint=models.CheckConstraint(
                condition=(models.Q(reviewed_by__isnull=False, reviewed_by_aesthetic_id__isnull=True) |
                           models.Q(reviewed_by__isnull=True, reviewed_by_aesthetic_id__isnull=False)),
                name='patient_decision_verified_actor',
            ),
        ),
    ]
