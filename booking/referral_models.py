from django.db import models


class ReferralEmailDelivery(models.Model):
    STATUS = [
        ("sent", "Versendet"),
        ("failed", "Fehlgeschlagen"),
    ]

    referrer_email = models.EmailField(db_index=True)
    invited_email = models.EmailField(db_index=True)
    referral_code = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=12, choices=STATUS)
    error = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        app_label = "booking"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["referrer_email", "-created_at"], name="book_ref_sender_time_idx"),
            models.Index(fields=["invited_email", "-created_at"], name="book_ref_invite_time_idx"),
        ]
        verbose_name = "Referral-E-Mail"
        verbose_name_plural = "Referral-E-Mails"

    def __str__(self):
        return f"{self.referrer_email} → {self.invited_email} ({self.status})"
