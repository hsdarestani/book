from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0016_appointment_reminder_24h_sent_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customer",
            name="salutation",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "Neutral / nicht angegeben"),
                    ("frau", "Frau"),
                    ("herr", "Herr"),
                    ("divers", "Divers"),
                ],
                default="",
                max_length=10,
                verbose_name="Anrede",
            ),
        ),
        migrations.AddField(
            model_name="appointment",
            name="reminder_1h_sent_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="1h-Erinnerung gesendet",
            ),
        ),
    ]
