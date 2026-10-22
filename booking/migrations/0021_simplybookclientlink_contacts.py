from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0020_simplybookclientlink')]

    operations = [
        migrations.AddField(
            model_name='simplybookclientlink',
            name='source_name',
            field=models.CharField(blank=True, default='', max_length=160),
        ),
        migrations.AddField(
            model_name='simplybookclientlink',
            name='source_email',
            field=models.CharField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='simplybookclientlink',
            name='source_phone',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
    ]
