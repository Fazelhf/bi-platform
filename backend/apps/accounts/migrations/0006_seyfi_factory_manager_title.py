"""
Retitle the production manager: مدیر تولید → مدیر کارخانه.

Done as a data migration so it lands on the live site through the normal
deploy (deploy.sh runs migrate) — the seed command and fixture only affect
fresh installs, and the server's row already exists.
"""
from django.db import migrations

OLD = "مدیر تولید"
NEW = "مدیر کارخانه"
USERNAME = "production_mgr"


def retitle(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(username=USERNAME, job_title_fa=OLD).update(job_title_fa=NEW)


def unretitle(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(username=USERNAME, job_title_fa=NEW).update(job_title_fa=OLD)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_user_avatar_image")]
    operations = [migrations.RunPython(retitle, unretitle)]
