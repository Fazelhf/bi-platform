"""
Rebuild both CRM datasets from scratch, in the one order that works.

Why a command rather than three commands in a row: the two loaders each clear
only their own half, and on a database whose rows were mislabelled by an
earlier migration the halves reference each other — a demo `DealItem` pointing
at a `Product` tagged real, which `PROTECT` then refuses to let go. Untangling
that by hand means running the right commands in the right order and knowing
why, which is not something anyone should have to work out on a production
server at speed.

This deletes everything CRM-side, both datasets, and rebuilds:

    real → the دیدار export in backend/data/didar
    demo → the generated showroom

    python manage.py reset_crm --yes
    python manage.py reset_crm --yes --skip-demo

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
    help = "پاک‌سازی کامل CRM و ساخت دوباره‌ی داده‌ی واقعی و نمایشی."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true",
            help="تأیید حذف همه‌ی داده‌ی CRM. بدون این، دستور اجرا نمی‌شود.",
        )
        parser.add_argument(
            "--skip-demo", action="store_true",
            help="فقط داده‌ی واقعی را وارد کن؛ داده‌ی نمایشی ساخته نشود.",
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

        if not options["skip_demo"]:
            self.stdout.write("\n▸ ساخت داده‌ی نمایشی…")
            call_command("seed_crm")

        self.stdout.write("")
        real = Customer.objects.filter(dataset="real").count()
        demo = Customer.objects.filter(dataset="demo").count()
        stray = Customer.objects.filter(dataset="real").exclude(
            code__startswith="didar-"
        ).count()
        self.stdout.write(self.style.SUCCESS(
            f"✔ واقعی: {real} مشتری · نمایشی: {demo} مشتری"
        ))
        if stray:
            # Should be zero by construction; if it is not, the tagging in
            # seed_crm has drifted again and the showroom is leaking into the
            # real file, which is worth shouting about rather than discovering
            # on a dashboard.
            self.stderr.write(
                f"⚠ {stray} مشتری با برچسب «واقعی» از دیدار نیامده — بررسی کنید."
            )
