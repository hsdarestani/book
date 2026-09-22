from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0015_close_qamar_september_2026"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="reminder_24h_sent_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="24h-Erinnerung gesendet",
            ),
        ),
    ]
