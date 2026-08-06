"""
A starting board for every section.

An empty canvas is a bad first impression of a builder: the manager cannot
tell whether there is nothing to show or nothing built yet, and "add your first
widget" teaches nothing about what the widgets can do. So each section opens on
a working board — the figures that section is actually judged by — which the
manager then rearranges, deletes from, or ignores entirely.

Idempotent: a section that already has a board is left alone, so this can be
re-run after a deploy without overwriting anyone's work. `--reset` is the
explicit way to ask for the starter board back.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.dashboards.models import Dashboard, Widget

SELECTED = {"mode": "selected"}
LAST_6 = {"mode": "last_n", "n": 6}
YEAR = {"mode": "year"}


def kpi(title, dataset, metric, x, y, w=3, h=3, **cfg):
    return {
        "kind": "kpi", "title": title, "x": x, "y": y, "w": w, "h": h,
        "config": {"dataset": dataset, "metrics": [metric], "time": SELECTED, **cfg},
    }


def chart(kind, title, dataset, metrics, dimension, x, y, w=6, h=6, **cfg):
    return {
        "kind": kind, "title": title, "x": x, "y": y, "w": w, "h": h,
        "config": {
            "dataset": dataset, "metrics": metrics, "dimension": dimension,
            "time": cfg.pop("time", SELECTED), **cfg,
        },
    }


def _sales_board(channel: str) -> list[dict]:
    """The four figures a sales manager is asked about, then the detail."""
    only = [{"dim": "channel", "op": "eq", "value": channel}]
    return [
        kpi("فروش ماه", "sales", "revenue", 0, 0, filters=only),
        kpi("تارگت ماه", "sales", "target", 3, 0, filters=only),
        kpi("سود", "sales", "profit", 6, 0, filters=only),
        kpi("وصولی", "sales", "collected", 9, 0, filters=only),
        {
            "kind": "progress", "title": "تحقق تارگت", "x": 0, "y": 3, "w": 6, "h": 3,
            "config": {"dataset": "sales", "metrics": ["revenue", "target"],
                       "time": SELECTED, "filters": only},
        },
        chart("bar", "فروش هر کارشناس", "sales", ["revenue", "target"], "employee",
              6, 3, 6, 6, filters=only, limit=10),
        chart("line", "روند فروش شش ماه", "sales", ["revenue", "target"], "month",
              0, 6, 6, 6, filters=only, time=LAST_6),
        chart("donut", "سهم هر تیم", "sales", ["revenue"], "team",
              0, 12, 4, 6, filters=only),
        {
            "kind": "table", "title": "جزئیات کارشناسان", "x": 4, "y": 12,
            "w": 8, "h": 6,
            "config": {
                "dataset": "sales",
                "metrics": ["revenue", "target", "profit", "invoice_count",
                            "new_customers"],
                "dimension": "employee", "time": SELECTED, "filters": only,
                "limit": 20,
            },
        },
    ]


BOARDS: dict[str, dict] = {
    "overview": {
        "title": "داشبورد مدیرعامل",
        "subtitle": "تصویر کلی شرکت در ماه انتخاب‌شده",
        "widgets": [
            kpi("فروش کل شرکت", "sales", "revenue", 0, 0),
            kpi("سود کل", "sales", "profit", 3, 0),
            kpi("تارگت", "sales", "target", 6, 0),
            kpi("تولید", "production", "output", 9, 0),
            chart("line", "روند فروش و تارگت", "sales", ["revenue", "target"], "month",
                  0, 3, 8, 6, time=YEAR),
            chart("donut", "ترکیب فروش بر اساس کانال", "sales", ["revenue"], "channel",
                  8, 3, 4, 6),
            chart("bar", "فروش استانی", "sales_province", ["sales", "target"],
                  "province", 0, 9, 6, 6, limit=10),
            chart("hbar", "شاخص‌های شرکت", "kpi", ["actual"], "kpi", 6, 9, 6, 6,
                  filters=[{"dim": "scope", "op": "eq", "value": "company"}],
                  limit=8),
        ],
    },
    "sales_team": {"title": "داشبورد فروش همکار", "widgets": _sales_board("team")},
    "sales_org": {"title": "داشبورد فروش بانکی", "widgets": _sales_board("organizational")},
    "sales_b2b": {"title": "داشبورد فروش B2B", "widgets": _sales_board("b2b")},
    "production": {
        "title": "داشبورد تولید",
        "widgets": [
            kpi("تولید ماه", "production", "output", 0, 0),
            kpi("شیفت فعال", "production", "shifts", 3, 0),
            kpi("میانگین ضایعات", "production", "waste_pct", 6, 0),
            kpi("هزینه تولید", "production_cost", "amount", 9, 0),
            chart("bar", "تولید هر خط", "production", ["output"], "machine",
                  0, 3, 6, 6, sort="natural"),
            chart("line", "روند تولید", "production", ["output"], "month",
                  6, 3, 6, 6, time=LAST_6),
            chart("donut", "ترکیب هزینه", "production_cost", ["amount"], "category",
                  0, 9, 5, 6),
            chart("bar", "توقفات هر خط", "production",
                  ["down_breakdown", "down_sizechange", "down_nowork"], "machine",
                  5, 9, 7, 6, sort="natural"),
        ],
    },
    "finance": {
        "title": "داشبورد مالی",
        "widgets": [
            kpi("دریافت ماه", "cash", "cash_in", 0, 0),
            kpi("پرداخت ماه", "cash", "cash_out", 3, 0),
            chart("bar", "دریافت و پرداخت ماهانه", "cash", ["cash_in", "cash_out"],
                  "month", 6, 0, 6, 6, time=LAST_6),
            chart("hbar", "سرفصل‌های پرداخت", "cash", ["amount"], "category",
                  0, 3, 6, 6,
                  filters=[{"dim": "direction", "op": "eq", "value": "out"}],
                  limit=10),
            chart("donut", "گردش هر حساب", "cash", ["amount"], "account", 0, 9, 5, 6),
            {
                "kind": "table", "title": "سرفصل‌ها به تفکیک جهت", "x": 5, "y": 9,
                "w": 7, "h": 6,
                "config": {"dataset": "cash", "metrics": ["amount"],
                           "dimension": "category", "split": "direction",
                           "time": SELECTED, "limit": 15},
            },
        ],
    },
    "commercial": {
        "title": "داشبورد بازرگانی",
        "widgets": [
            kpi("ارزش سفارش‌های ماه", "purchase_orders", "value", 0, 0),
            kpi("تعداد سفارش", "purchase_orders", "orders", 3, 0),
            kpi("درخواست‌های خرید", "purchase_requests", "requests", 6, 0),
            chart("bar", "خرید از هر تامین‌کننده", "purchase_orders", ["value"],
                  "supplier", 0, 3, 6, 6, limit=10),
            chart("donut", "خرید بر اساس گروه کالا", "purchase_orders", ["value"],
                  "material_category", 6, 3, 6, 6),
            chart("line", "روند خرید", "purchase_orders", ["value"], "month",
                  0, 9, 12, 5, time=LAST_6),
        ],
    },
    "crm": {
        "title": "داشبورد CRM",
        "widgets": [
            kpi("فرصت‌های ماه", "crm_deals", "deals", 0, 0),
            kpi("مبلغ موفق", "crm_deals", "won_amount", 3, 0),
            kpi("سود", "crm_deals", "profit", 6, 0),
            kpi("مشتریان", "crm_customers", "customers", 9, 0, time={"mode": "all"}),
            chart("bar", "قیف فروش", "crm_deals", ["amount"], "stage", 0, 3, 6, 6,
                  sort="natural", time={"mode": "all"}),
            chart("donut", "منبع سرنخ", "crm_deals", ["deals"], "lead_source",
                  6, 3, 6, 6, time={"mode": "all"}),
            chart("hbar", "دلایل شکست", "crm_deals", ["deals"], "lost_reason",
                  0, 9, 6, 6, filters=[{"dim": "status", "op": "eq", "value": "lost"}],
                  time={"mode": "all"}),
            chart("bar", "عملکرد کارشناسان", "crm_deals", ["won_amount", "amount"],
                  "owner", 6, 9, 6, 6, time={"mode": "all"}),
        ],
    },
}


class Command(BaseCommand):
    help = "چیدمان اولیه داشبورد هر بخش را می‌سازد (بدون بازنویسی چیدمان موجود)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="چیدمان پیش‌فرض هر بخش را دور بریز و از نو بساز.",
        )
        parser.add_argument(
            "--section", default="", help="فقط یک بخش را بساز."
        )

    @transaction.atomic
    def handle(self, *args, **options):
        only = options["section"]
        created = skipped = 0

        for section, spec in BOARDS.items():
            if only and section != only:
                continue
            existing = Dashboard.objects.filter(section=section, is_default=True).first()
            if existing and not options["reset"]:
                skipped += 1
                self.stdout.write(f"— {section}: چیدمان موجود دست‌نخورده ماند")
                continue
            if existing:
                existing.widgets.all().delete()
                existing.delete()

            board = Dashboard.objects.create(
                section=section,
                title=spec["title"],
                subtitle=spec.get("subtitle", ""),
                is_default=True,
                is_published=True,
            )
            Widget.objects.bulk_create([
                Widget(
                    dashboard=board, sort_order=i,
                    kind=w["kind"], title=w.get("title", ""),
                    subtitle=w.get("subtitle", ""),
                    x=w["x"], y=w["y"], w=w["w"], h=w["h"],
                    config=w.get("config", {}), options=w.get("options", {}),
                )
                for i, w in enumerate(spec["widgets"])
            ])
            created += 1
            self.stdout.write(self.style.SUCCESS(
                f"✓ {section}: «{board.title}» با {len(spec['widgets'])} ویجت"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\n{created} داشبورد ساخته شد، {skipped} بخش دست‌نخورده."
        ))
