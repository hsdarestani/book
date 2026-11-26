from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0030_office_intake_forms')]
    operations = [
        migrations.AddField(
            model_name='mobilestaffcancellation',
            name='notification_independent',
            field=models.BooleanField(default=False),
        ),
    ]
