from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0027_correct_returning_botox_buffer')]
    operations = [
        migrations.AddField(
            model_name='customer',
            name='date_of_birth',
            field=models.DateField('Geburtsdatum', null=True, blank=True),
        ),
    ]
