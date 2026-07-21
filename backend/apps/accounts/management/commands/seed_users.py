"""
Seed the platform's real user list: one CEO, four department managers, and one
system admin (the site owner). EVERY other account is deactivated — specialists
(کارشناس) do not have site access.

All demo passwords are 'demo12345' — change in any real deployment.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import Department, Role, User

# username, display, role, department, job_title, color
MANAGERS = [
    ("ceo", "امیر عصاری", Role.EXECUTIVE, Department.NONE, "مدیرعامل", "#10b981"),
    ("sales_team_mgr", "محمدمحسن شاهان", Role.MANAGER, Department.SALES_TEAM, "مدیر فروش همکار", "#3b6fed"),
    ("banking_mgr", "هانیه منزه", Role.MANAGER, Department.SALES_ORG, "مدیر فروش بانکی", "#f59e0b"),
    ("b2b_mgr", "سارا مسگرچیان", Role.MANAGER, Department.SALES_B2B, "مدیر فروش B2B", "#ec4899"),
    ("production_mgr", "محمد مهدی صیفی", Role.MANAGER, Department.PRODUCTION, "مدیر تولید", "#8b5cf6"),
]
ADMIN_USERNAME = "admin"
ADMIN_DISPLAY = "مدیر سیستم"
PASSWORD = "demo12345"


class Command(BaseCommand):
    help = "Seed the 5 managers + 1 admin; deactivate all other accounts."

    def handle(self, *args, **options):
        keep = {ADMIN_USERNAME}
        for username, display, role, dept, title, color in MANAGERS:
            keep.add(username)
            user, created = User.objects.get_or_create(username=username)
            user.display_name_fa = display
            user.job_title_fa = title
            user.avatar_color = color
            user.role = role
            user.department = dept
            user.is_active = True
            user.is_staff = False
            user.is_superuser = False
            user.set_password(PASSWORD)
            user.save()
            self.stdout.write(f"  {'created' if created else 'updated'}: {username} ({display})")

        # The site owner / admin (superuser).
        admin, _ = User.objects.get_or_create(username=ADMIN_USERNAME)
        admin.display_name_fa = ADMIN_DISPLAY
        admin.job_title_fa = "ادمین سیستم"
        admin.avatar_color = "#1c1c1e"
        admin.role = Role.EXECUTIVE  # sees dashboards too
        admin.is_active = admin.is_staff = admin.is_superuser = True
        admin.set_password(PASSWORD)
        admin.save()

        # Everyone else (کارشناس / old demo accounts) loses access.
        deactivated = User.objects.exclude(username__in=keep).update(is_active=False)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(MANAGERS)} managers + admin; deactivated {deactivated} "
            f"other account(s). Password: {PASSWORD}"
        ))
