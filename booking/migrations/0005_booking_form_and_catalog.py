from django.db import migrations, models


def update_catalog(apps, schema_editor):
    Service = apps.get_model('booking', 'Service')
    StaffMember = apps.get_model('booking', 'StaffMember')

    definitions = [
        ('Ästhetische Erstberatung', 'aesthetische-erstberatung', 30, 10, 'Individuelle Beratung', 10),
        ('Botox - Neupatient', 'botox-neupatient', 30, 10, 'ab 119 €', 20),
        ('Botox - Bestandspatient', 'botox-bestandspatient', 15, 10, 'ab 119 €', 30),
        ('Hyaluron', 'hyaluron', 30, 10, 'ab 220 €', 40),
        ('Laser-Haarentfernung', 'laser-haarentfernung', 45, 10, 'ab 49 €', 50),
        ('RF-Microneedling', 'rf-microneedling', 60, 15, 'ab 700 €', 60),
        ('Skinbooster', 'skinbooster', 30, 10, 'ab 220 €', 70),
        ('Infusionstherapie', 'infusionstherapie', 30, 10, 'ab 99 €', 80),
        ('Injektionslipolyse', 'injektionslipolyse', 30, 10, 'ab 250 €', 90),
        ('Kontrolltermin', 'kontrolltermin', 15, 5, '', 100),
    ]
    descriptions = {
        'aesthetische-erstberatung': 'Persönliche ästhetische Erstberatung bei A+esthetic.',
        'botox-neupatient': 'Botox-Termin für neue Patientinnen und Patienten.',
        'botox-bestandspatient': 'Botox-Termin für bestehende Patientinnen und Patienten.',
        'hyaluron': 'Hyaluron-Behandlung bei A+esthetic.',
        'laser-haarentfernung': 'Laser-Haarentfernung bei A+esthetic.',
        'rf-microneedling': 'RF-Microneedling bei A+esthetic.',
        'skinbooster': 'Skinbooster-Behandlung bei A+esthetic.',
        'infusionstherapie': 'Infusionstherapie bei A+esthetic.',
        'injektionslipolyse': 'Injektionslipolyse bei A+esthetic.',
        'kontrolltermin': 'Kontrolltermin nach deiner Behandlung.',
    }

    active_services = []
    for name, slug, duration, buffer, price, order in definitions:
        service, _ = Service.objects.update_or_create(
            slug=slug,
            defaults={
                'name': name,
                'description': descriptions[slug],
                'duration_minutes': duration,
                'buffer_minutes': buffer,
                'price_label': price,
                'active': True,
                'bookable': True,
                'sort_order': order,
            },
        )
        active_services.append(service)

    keep_slugs = [item[1] for item in definitions]
    Service.objects.exclude(slug__in=keep_slugs).update(active=False, bookable=False)
    Service.objects.filter(slug='prp-beratung').update(active=False, bookable=False)

    for staff in StaffMember.objects.filter(active=True):
        staff.services.set(active_services)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('booking', '0004_rename_qamar_hameed')]
    operations = [
        migrations.AddField(model_name='appointment', name='returning_customer', field=models.BooleanField(default=False, verbose_name='Schon einmal bei uns')),
        migrations.AddField(model_name='appointment', name='referral_source', field=models.CharField(blank=True, max_length=100, verbose_name='Wie auf uns aufmerksam geworden')),
        migrations.AddField(model_name='appointment', name='marketing_opt_in', field=models.BooleanField(default=True, verbose_name='Marketing-Einwilligung')),
        migrations.AddField(model_name='appointment', name='cancellation_terms_accepted', field=models.BooleanField(default=False, verbose_name='Stornierungsbedingungen akzeptiert')),
        migrations.AddField(model_name='appointment', name='privacy_accepted', field=models.BooleanField(default=False, verbose_name='Datenschutz bestätigt')),
        migrations.RunPython(update_catalog, noop_reverse),
    ]
