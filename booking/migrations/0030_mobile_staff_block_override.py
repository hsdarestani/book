from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('booking', '0029_native_identity_review_actor'),
    ]

    operations = [
        migrations.CreateModel(
            name='MobileStaffBlockOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_marker', models.CharField(max_length=256, unique=True)),
                ('block_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('actor_id', models.PositiveBigIntegerField()),
                ('deleted', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
