from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('pms_app', '0006_pteam'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='supervisors',
            field=models.ManyToManyField(
                blank=True,
                related_name='supervised_projects',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]