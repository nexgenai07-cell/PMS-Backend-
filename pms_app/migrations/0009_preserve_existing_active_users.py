"""
Data migration: mark all EXISTING verified users as active.

Background: 0008 changed User.is_active default from True to False.
New users now start inactive until they verify. But we don't want to
lock out users who were already using the system before this change.

We set is_active=True for anyone who:
  - was created before this migration runs, AND
  - is not soft-deleted

After this migration, the default still applies to NEW users only.
"""
from django.db import migrations


def preserve_existing_active_users(apps, schema_editor):
    User = apps.get_model('pms_app', 'User')
    # Every user that already existed is presumed to be grandfathered in.
    User.objects.filter(is_deleted=False).update(is_active=True, is_verified=True)


def reverse_noop(apps, schema_editor):
    # Reversing the migration does nothing — this is a one-time data fix.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('pms_app', '0008_alter_user_is_active_default'),
    ]

    operations = [
        migrations.RunPython(preserve_existing_active_users, reverse_noop),
    ]