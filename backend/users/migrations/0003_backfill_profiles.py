from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    """Users created before profiles existed get one, named after their email's local part."""
    User = apps.get_model("users", "User")
    UserProfile = apps.get_model("users", "UserProfile")
    missing = User.objects.filter(profile__isnull=True)
    UserProfile.objects.bulk_create(
        UserProfile(user=user, display_name=user.email.split("@")[0][:80])
        for user in missing.iterator()
    )


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0002_profiles_and_sessions"),
    ]

    operations = [
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
    ]
