from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0011_reassign_simplybook_to_ariane"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferralEmailDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("referrer_email", models.EmailField(db_index=True, max_length=254)),
                ("invited_email", models.EmailField(db_index=True, max_length=254)),
                ("referral_code", models.CharField(db_index=True, max_length=32)),
                ("status", models.CharField(choices=[("sent", "Versendet"), ("failed", "Fehlgeschlagen")], max_length=12)),
                ("error", models.CharField(blank=True, max_length=500)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "verbose_name": "Referral-E-Mail",
                "verbose_name_plural": "Referral-E-Mails",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="referralemaildelivery",
            index=models.Index(fields=["referrer_email", "-created_at"], name="book_ref_sender_time_idx"),
        ),
        migrations.AddIndex(
            model_name="referralemaildelivery",
            index=models.Index(fields=["invited_email", "-created_at"], name="book_ref_invite_time_idx"),
        ),
    ]
