from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('booking', '0026_office_intake_forms')]
    operations = [
        migrations.AddField(model_name='appointment', name='simplybook_booking_id', field=models.CharField(max_length=80,unique=True,null=True,blank=True,editable=False)),
        migrations.AddField(model_name='appointment', name='simplybook_sync_state', field=models.CharField(max_length=20,blank=True,default='',editable=False)),
        migrations.AddField(model_name='appointment', name='simplybook_event_id', field=models.CharField(max_length=80,blank=True,default='',editable=False)),
        migrations.AddField(model_name='appointment', name='simplybook_client_id', field=models.CharField(max_length=80,blank=True,default='',editable=False)),
    ]
