"""
Attach login accounts to salespeople (DimEmployee.user).

The employee dimension was built from spreadsheet column headers, so it and
the user table only ever agreed by coincidence of spelling. CRM data entry
needs a real link: whoever is logged in has to resolve to the salesperson a
new deal or call belongs to.

Matching is by Persian display name, which is exact for the current data.
Anything ambiguous is reported rather than guessed — a wrong link would
silently file one rep's deals under another's name.
"""
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.sales.models import DimEmployee


class Command(BaseCommand):
    help = "لینک کردن حساب‌های کاربری به کارشناسان فروش (بر اساس نام نمایشی)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", help="فقط گزارش بده، تغییری نده"
        )
        parser.add_argument(
            "--create-missing", action="store_true",
            help="ساخت حساب کاربری محلی برای کارشناسانی که حساب ندارند (فقط برای محیط توسعه)",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        employees = list(DimEmployee.objects.filter(is_active=True))
        by_name: dict[str, list[DimEmployee]] = {}
        for e in employees:
            by_name.setdefault(e.full_name_fa.strip(), []).append(e)

        linked = skipped = ambiguous = 0
        for user in User.objects.exclude(display_name_fa=""):
            matches = by_name.get(user.display_name_fa.strip(), [])
            if not matches:
                continue
            if len(matches) > 1:
                ambiguous += 1
                self.stdout.write(self.style.WARNING(
                    f"  ? «{user.display_name_fa}» به {len(matches)} کارشناس می‌خورد — رد شد"
                ))
                continue
            emp = matches[0]
            if emp.user_id and emp.user_id != user.id:
                skipped += 1
                continue
            if emp.user_id == user.id:
                continue
            if not dry:
                emp.user = user
                emp.save(update_fields=["user"])
            linked += 1
            self.stdout.write(f"  ✓ {user.username} → {emp.full_name_fa}")

        missing = list(
            DimEmployee.objects.filter(is_active=True, user__isnull=True)
            .exclude(full_name_fa__in=["", "0"])
        )
        if opts["create_missing"] and not dry:
            created = self._create_accounts(missing)
            missing = [e for e in missing if e not in created]

        unlinked = [e.full_name_fa for e in missing]
        self.stdout.write(self.style.SUCCESS(
            f"{'(آزمایشی) ' if dry else ''}{linked} لینک شد"
            + (f"، {ambiguous} مبهم" if ambiguous else "")
            + (f"، {skipped} از قبل به کاربر دیگری وصل بود" if skipped else "")
        ))
        if unlinked:
            self.stdout.write(
                "کارشناسان بدون حساب کاربری: " + "، ".join(unlinked)
                + "\n(برای ساخت حساب محلی: manage.py link_employees --create-missing)"
            )

    # ------------------------------------------------------------------
    def _create_accounts(self, employees) -> list:
        """
        Local demo accounts for reps who have none, so data entry can be tried
        end-to-end. Opt-in only, and it uses the same throwaway password the
        rest of the local seed data uses — never run this against production.
        """
        from django.utils.crypto import get_random_string

        created = []
        for emp in employees:
            base = f"rep{emp.pk}"
            username = base
            while User.objects.filter(username=username).exists():
                username = f"{base}-{get_random_string(4).lower()}"
            user = User.objects.create_user(
                username=username,
                password="demo12345",  # local demo convention, same as seed_users
                display_name_fa=emp.full_name_fa,
                role="operator",
                department="sales_team",
                job_title_fa="کارشناس فروش",
            )
            emp.user = user
            emp.save(update_fields=["user"])
            created.append(emp)
            self.stdout.write(self.style.SUCCESS(
                f"  + حساب «{username}» برای {emp.full_name_fa} ساخته شد"
            ))
        return created
