from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0017_customer_divers_appointment_reminder_1h"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExternalSyncState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source", models.CharField(max_length=40, unique=True)),
                (
                    "baseline_completed_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "last_success_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={
                "verbose_name": "Externer Sync-Status",
                "verbose_name_plural": "Externe Sync-Status",
            },
        ),
    ]
