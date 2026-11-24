from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('booking','0029_native_identity_review_actor'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    # Equivalent schema already provided by the deployed web intake migration.
    operations = []
