from django.db import migrations


def correct_brand_spelling(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    for service in Service.objects.all().only('pk', 'description'):
        corrected = (service.description or '').replace('A+esthetic', 'A+Esthetic').replace('A+ Esthetic', 'A+Esthetic')
        if corrected != service.description:
            Service.objects.filter(pk=service.pk).update(description=corrected)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('booking', '0005_booking_form_and_catalog')]
    operations = [migrations.RunPython(correct_brand_spelling, noop_reverse)]
