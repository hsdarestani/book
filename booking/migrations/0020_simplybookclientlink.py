from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('booking', '0019_doctorpatientaccess')]

    operations = [
        migrations.CreateModel(
            name='SimplyBookClientLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('external_client_id', models.CharField(max_length=80, unique=True)),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='simplybook_client_links', to='booking.customer'
                )),
            ],
            options={
                'verbose_name': 'SimplyBook-Kundenverknüpfung',
                'verbose_name_plural': 'SimplyBook-Kundenverknüpfungen',
            },
        ),
    ]
