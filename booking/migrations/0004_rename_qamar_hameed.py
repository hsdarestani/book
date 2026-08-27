from django.db import migrations


def rename_provider(apps, schema_editor):
    StaffMember = apps.get_model('booking', 'StaffMember')
    StaffMember.objects.filter(display_name='A+esthetic Arzt').update(display_name='Qamar Hameed')


def reverse_rename(apps, schema_editor):
    StaffMember = apps.get_model('booking', 'StaffMember')
    StaffMember.objects.filter(display_name='Qamar Hameed').update(display_name='A+esthetic Arzt')


class Migration(migrations.Migration):
    dependencies = [('booking', '0003_doctor_providers')]
    operations = [migrations.RunPython(rename_provider, reverse_rename)]
