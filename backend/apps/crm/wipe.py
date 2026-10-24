"""
«پاک‌سازی داده» — empty CRM before loading it again from آرپا and دیدار.

What goes is everything an upload brings in again: invoices, deals and their
lines, activities, tasks, feedback, the pipeline's stages and its lead
sources, lost reasons and tags, and the import history.

What stays, deliberately:

* **Customers** — the customer list the team has now, with their آرپا and
  دیدار codes, so the next upload finds each account instead of making a
  second one.
* **Products** — فروش ۲'s price lists, costs and product profiles hang off
  them, and some of those links delete along with the product.
* **بازبینی تطبیق**'s queue and dismissals — decisions people made about
  which records are the same customer.
"""
from __future__ import annotations

from django.db import transaction

from apps.crm.models import (
    Activity, Customer, CustomerFeedback, Deal, DealItem, DealStageEvent,
    DemoProvinceTarget, ImportBatch, LeadSource, LostReason, PipelineStage,
    SalesInvoice, SalesInvoiceItem, Tag, Task,
)

#: Children before parents, with the label shown on the page.
ORDER = (
    (SalesInvoiceItem, "ردیف فاکتور"),
    (SalesInvoice, "فاکتور آرپا"),
    (ImportBatch, "سابقه‌ی ورود فایل"),
    (DealStageEvent, "تاریخچه‌ی مرحله‌ی معامله"),
    (DealItem, "ردیف معامله"),
    (Activity, "فعالیت و یادداشت"),
    (Task, "کار و یادآوری"),
    (CustomerFeedback, "بازخورد مشتری"),
    (Deal, "معامله"),
    (PipelineStage, "مرحله‌ی کاریز"),
    (LeadSource, "منبع سرنخ"),
    (LostReason, "دلیل شکست"),
    (Tag, "برچسب"),
    (DemoProvinceTarget, "تارگت نمایشی استان"),
)

#: The phrase that has to be typed — a button alone is one slip away.
CONFIRM = "پاک شود"


def counts() -> dict:
    return {
        "remove": [
            {"key": m.__name__, "label": label, "count": m.objects.count()}
            for m, label in ORDER
        ],
        "keep": {"customers": Customer.objects.count()},
        "confirm": CONFIRM,
    }


def wipe() -> dict:
    """Delete it all in one transaction; reset what customers derived from it."""
    removed = {}
    with transaction.atomic():
        for model, label in ORDER:
            removed[label] = model.objects.all().delete()[0]
        # Facts about deals and activities that no longer exist.
        Customer.objects.update(first_deal_won_at=None, last_activity_at=None)
    return removed
