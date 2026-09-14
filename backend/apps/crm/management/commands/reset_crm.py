"""
Rebuild the CRM from scratch, in the one order that works.

This deletes everything CRM-side and re-imports the دیدار export in
backend/data/didar. Deletion order matters: `PROTECT` on DealItem.product and
on the dimension keys refuses a parent while a child still points at it.

    python manage.py reset_crm --yes

(There used to be a generated demo set as well. It was removed; this command
also clears any demo rows an old database still holds.)

It refuses to run without --yes, and it says what it is about to destroy
first. It is a repair tool, not part of deploy: `deploy.sh` calls the two
loaders with --if-empty, which never delete anything.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.crm.models import (
    Activity,
    Customer,
    CustomerFeedback,
    CustomerGroup,
    Deal,
    DealItem,
    DealStageEvent,
    DemoProvinceTarget,
    LeadSource,
    LostReason,
    PipelineStage,
    Product,
    ProductCategory,
    Tag,
    Task,
)

#: Children before parents. `PROTECT` on DealItem.product and on the
#: dimension keys means order here is load-bearing, not cosmetic.
ORDER = (
    DealStageEvent, DealItem, Activity, Task, CustomerFeedback,
    Deal, Customer, Product, ProductCategory, PipelineStage,
    LeadSource, LostReason, Tag, CustomerGroup, DemoProvinceTarget,
)


class Command(BaseCommand):
    help = "پاک‌سازی کامل CRM و ورود دوباره‌ی داده‌ی واقعی از دیدار."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="تأیید حذف همه‌ی داده‌ی CRM. بدون این، دستور اجرا نمی‌شود.",
        )
        parser.add_argument(
            "--dir", default=None, help="پوشه‌ی خروجی‌های دیدار.",
        )

    def handle(self, *args, **options):
        counts = {m.__name__: m.objects.count() for m in ORDER}
        live = {k: v for k, v in counts.items() if v}

        self.stdout.write("این دستور همه‌ی داده‌ی CRM را پاک می‌کند:")
        for name, n in live.items():
            self.stdout.write(f"  {name}: {n}")
        if not live:
            self.stdout.write("  (چیزی برای پاک کردن نیست)")

        if not options["yes"]:
            self.stderr.write(
                "\nبرای اجرا --yes را اضافه کنید. هیچ تغییری داده نشد."
            )
            return

        with transaction.atomic():
            for model in ORDER:
                model.objects.all().delete()
        self.stdout.write(self.style.WARNING("همه‌ی داده‌ی CRM پاک شد."))

        self.stdout.write("\n▸ وارد کردن داده‌ی واقعی از دیدار…")
        import_kwargs = {"fresh": False}
        if options["dir"]:
            import_kwargs["dir"] = options["dir"]
        call_command("import_didar_crm", **import_kwargs)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"✔ {Customer.objects.count()} مشتری وارد شد."
        ))
