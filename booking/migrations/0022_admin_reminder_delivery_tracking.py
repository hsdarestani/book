from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0021_simplybookclientlink_contacts')]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='reminder_1h_admin_email_sent_at',
            field=models.DateTimeField('1h-Admin-Erinnerung E-Mail gesendet', null=True, blank=True, editable=False),
        ),
        migrations.AddField(
            model_name='appointment',
            name='reminder_1h_admin_push_sent_at',
            field=models.DateTimeField('1h-Admin-Erinnerung Push gesendet', null=True, blank=True, editable=False),
        ),
    ]
