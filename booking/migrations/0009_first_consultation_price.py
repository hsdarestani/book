from django.db import migrations


def set_first_consultation_price(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    Service.objects.filter(slug='aesthetische-erstberatung').update(price_label='30 €')


def restore_first_consultation_price(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    Service.objects.filter(slug='aesthetische-erstberatung').update(price_label='Individuelle Beratung')


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0008_patient_record_sync_fields'),
    ]

    operations = [
        migrations.RunPython(set_first_consultation_price, restore_first_consultation_price),
    ]
