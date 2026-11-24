"""Preserve the 15-minute returning-patient Botox service on fresh databases."""
from django.db import migrations


def correct_legacy_buffer(apps, schema_editor):
    Service = apps.get_model("booking", "Service")
    # Correct only the historical seeded configuration. Do not touch existing
    # appointment times or overwrite unrelated administrator customizations.
    Service.objects.using(schema_editor.connection.alias).filter(
        slug="botox-bestandspatient", duration_minutes=15, buffer_minutes=10,
    ).update(buffer_minutes=0)


class Migration(migrations.Migration):
    dependencies = [("booking", "0026_mobile_staff_commands")]
    operations = [
        migrations.RunPython(correct_legacy_buffer, migrations.RunPython.noop),
    ]
