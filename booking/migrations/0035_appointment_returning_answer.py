from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0034_patient_form_notification_read')]
    operations = [
        migrations.AddField(model_name='appointment', name='returning_customer_answered',
                            field=models.BooleanField(default=False, null=True, editable=False)),
    ]
