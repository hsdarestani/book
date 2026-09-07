from datetime import date, time

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_october_and_templates(apps, schema_editor):
    Staff = apps.get_model('booking', 'StaffMember')
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Access = apps.get_model('booking', 'AdminAccessProfile')
    Template = apps.get_model('booking', 'WhatsAppTemplate')

    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if qamar:
        for day in (2, 3, 4, 12, 13, 14, 19, 20, 21, 24, 25, 26, 27):
            Override.objects.update_or_create(
                staff=qamar,
                date=date(2026, 10, day),
                defaults={
                    'closed': False,
                    'start_time_1': time(12, 0),
                    'end_time_1': time(18, 0),
                    'start_time_2': None,
                    'end_time_2': None,
                },
            )
        candidates = User.objects.filter(
            models.Q(username__icontains='qamar')
            | models.Q(email__icontains='qamar')
            | models.Q(first_name__icontains='qamar')
            | models.Q(last_name__icontains='hameed')
        )
        for user in candidates:
            Access.objects.update_or_create(user=user, defaults={'staff': qamar, 'view_only': True})

    defaults = [
        ('Termin-Erinnerung', 'Hallo {anrede} {nachname}, wir möchten Sie kurz an Ihren Termin bei A+ Esthetic erinnern.'),
        ('Nachsorge', 'Hallo {vorname}, wir hoffen, dass es Ihnen nach Ihrem Termin gut geht. Wenn Sie Fragen haben, schreiben Sie uns gerne.'),
        ('Rückruf', 'Hallo {vorname}, hier ist A+ Esthetic. Wir wollten uns kurz bei Ihnen melden. Wann passt Ihnen ein Rückruf?'),
    ]
    for index, (name, body) in enumerate(defaults, start=1):
        Template.objects.get_or_create(name=name, defaults={'body': body, 'sort_order': index * 10, 'active': True})


def reverse_seed(apps, schema_editor):
    Override = apps.get_model('booking', 'DailyAvailabilityOverride')
    Staff = apps.get_model('booking', 'StaffMember')
    qamar = Staff.objects.filter(display_name__iexact='Qamar Hameed').first()
    if qamar:
        Override.objects.filter(
            staff=qamar,
            date__year=2026,
            date__month=10,
            date__day__in=[2, 3, 4, 12, 13, 14, 19, 20, 21, 24, 25, 26, 27],
        ).delete()


class Migration(migrations.Migration):
    dependencies = [('booking', '0012_referral_email_delivery')]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='salutation',
            field=models.CharField(
                blank=True,
                choices=[('', 'Neutral / nicht angegeben'), ('frau', 'Frau'), ('herr', 'Herr')],
                default='',
                max_length=10,
                verbose_name='Anrede',
            ),
        ),
        migrations.CreateModel(
            name='WhatsAppTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='Name')),
                ('body', models.TextField(help_text='Variablen: {anrede}, {vorname}, {nachname}, {name}', verbose_name='Text')),
                ('active', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='Reihenfolge')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'WhatsApp-Vorlage', 'verbose_name_plural': 'WhatsApp-Vorlagen', 'ordering': ['sort_order', 'name']},
        ),
        migrations.CreateModel(
            name='AdminAccessProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('view_only', models.BooleanField(default=False, verbose_name='Nur ansehen')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('staff', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='admin_access_profiles', to='booking.staffmember')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='aesthetic_access', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunPython(seed_october_and_templates, reverse_seed),
    ]
