"""
Seed demo users covering both personas: one CEO (views all dashboards, enters
nothing) and three department managers (each enters only their section).

All demo passwords are 'demo12345' — change in any real deployment.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import Department, Role, User

DEMO_USERS = [
    # username, display, role, department, job_title, color
    ("ceo", "بهرام زمانی", Role.EXECUTIVE, Department.NONE, "مدیرعامل", "#10b981"),
    ("prod_manager", "مسعود کمالی", Role.MANAGER, Department.PRODUCTION, "مدیر تولید", "#3b6fed"),
    ("org_manager", "سهراب بهروزی", Role.MANAGER, Department.SALES_ORG, "مدیر فروش سازمانی", "#f59e0b"),
    ("team_manager", "هانیه منزه", Role.MANAGER, Department.SALES_TEAM, "مدیر تیم فروش", "#ec4899"),
    # A few extra colleagues so chat / team directory have people.
    ("s.mousavi", "صبا موسوی", Role.OPERATOR, Department.SALES_TEAM, "کارشناس فروش", "#8b5cf6"),
    ("m.momeni", "مهدیس مومنی", Role.OPERATOR, Department.SALES_TEAM, "کارشناس فروش", "#06b6d4"),
    ("a.rezaei", "علی رضایی", Role.OPERATOR, Department.PRODUCTION, "اپراتور خط تولید", "#ef4444"),
]
PASSWORD = "demo12345"


class Command(BaseCommand):
    help = "Seed demo CEO + department-manager users."

    def handle(self, *args, **options):
        for username, display, role, dept, title, color in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            user.display_name_fa = display
            user.job_title_fa = title
            user.avatar_color = color
            user.role = role
            user.department = dept
            # Demo personas are NOT superusers — otherwise they'd bypass the
            # very permission rules this seeds, hiding the read-only CEO role.
            user.is_staff = False
            user.is_superuser = False
            user.set_password(PASSWORD)
            user.save()
            self.stdout.write(
                f"  {'created' if created else 'updated'}: {username} "
                f"({role}/{dept or '—'})"
            )

        # A real superuser for the Django admin, separate from the demo CEO.
        admin, _ = User.objects.get_or_create(
            username="admin", defaults={"display_name_fa": "مدیر سیستم"}
        )
        admin.is_staff = admin.is_superuser = True
        admin.set_password(PASSWORD)
        admin.save()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(DEMO_USERS)} demo users + 1 admin. Password: {PASSWORD}"
        ))
