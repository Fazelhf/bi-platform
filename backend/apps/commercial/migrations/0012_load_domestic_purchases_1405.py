"""
Load بازرگانی داخلی's real 1405 purchasing history.

A data migration on purpose, unlike the demo seed: this is the company's own
record — read once from the department's «Domestic purchase 1405» folder (the
«استعلام قیمت» workbook, the Misito letters, proformas and warehouse receipts)
and frozen into `data/domestic_purchases_1405.json`. `deploy.sh` runs
`migrate`, so the server gets it without anyone touching the spreadsheet
again; from here on purchases are entered in the app.

Safe on any database:

* Runs once — if a document carrying the import tag already exists, it does
  nothing, so a database that got the data another way is not doubled.
* Materials and suppliers are matched by code, then by Persian name, before
  anything is created, so a supplier someone already typed in is reused rather
  than duplicated.
* Document numbers come from the same per-year counters the app uses, so
  they continue whatever series the server already has.

Reversing it removes exactly the documents it wrote (by the tag); materials
and suppliers stay, since other records may point at them by then.
"""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.db import migrations

from apps.core import jalali

DATA = Path(__file__).resolve().parent.parent / "data" / "domestic_purchases_1405.json"


def _d(text):
    return date.fromisoformat(text) if text else None


def load(apps, schema_editor):
    Material = apps.get_model("commercial", "Material")
    MaterialCategory = apps.get_model("commercial", "MaterialCategory")
    Supplier = apps.get_model("commercial", "Supplier")
    PaymentTerm = apps.get_model("commercial", "PaymentTerm")
    QuoteReason = apps.get_model("commercial", "QuoteReason")
    PurchaseRequest = apps.get_model("commercial", "PurchaseRequest")
    Quote = apps.get_model("commercial", "Quote")
    PurchaseOrder = apps.get_model("commercial", "PurchaseOrder")
    Sample = apps.get_model("commercial", "Sample")
    DocumentCounter = apps.get_model("commercial", "DocumentCounter")
    DimPeriod = apps.get_model("core", "DimPeriod")

    data = json.loads(DATA.read_text(encoding="utf-8"))
    tag = data["tag"]
    if PurchaseOrder.objects.filter(note__contains=tag).exists():
        return

    def tagged(note):
        return f"{note} {tag}".strip()

    # Historical models have no custom save(), so numbering is done here with
    # the same counter table models._next_number uses.
    def number(prefix, on):
        year = jalali.from_gregorian(on)[0]
        counter, _ = DocumentCounter.objects.get_or_create(prefix=prefix, jalali_year=year)
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
        return f"{prefix}-{year}-{counter.last_value:04d}"

    periods = {
        (p.jalali_year, p.jalali_month): p
        for p in DimPeriod.objects.filter(kind="month")
    }

    def period(on):
        jy, jm, _ = jalali.from_gregorian(on)
        return periods.get((jy, jm))

    def match(model, row, fields):
        obj = (model.objects.filter(code=row["code"]).first()
               or model.objects.filter(name_fa=row["name_fa"]).first())
        if obj:
            return obj
        return model.objects.create(code=row["code"], name_fa=row["name_fa"], **fields)

    categories = {c.code: c for c in MaterialCategory.objects.all()}
    materials = {
        m["code"]: match(Material, m, {
            "category": categories.get(m["category"]), "unit": m["unit"],
        })
        for m in data["materials"]
    }
    suppliers = {
        s["code"]: match(Supplier, s, {
            "origin": "domestic",
            **{k: s[k] for k in ("contact_name", "mobile", "phone", "email",
                                  "address", "activity", "note")},
        })
        for s in data["suppliers"]
    }
    for t in data["payment_terms"]:
        PaymentTerm.objects.get_or_create(code=t["code"], defaults={
            "name_fa": t["name_fa"], "advance_pct": Decimal(t["advance_pct"]),
            "days": t["days"], "sort_order": 50,
        })
    terms = {t.code: t for t in PaymentTerm.objects.all()}
    reasons = {r.code: r for r in QuoteReason.objects.all()}

    requests = {}
    for r in data["requests"]:
        on = _d(r["requested_on"])
        req = PurchaseRequest.objects.create(
            request_no=number("PR", on), material=materials[r["material"]],
            quantity=Decimal(r["quantity"]), requested_on=on, period=period(on),
            status=r["status"], note=tagged(r["note"]),
        )
        quotes = {}
        for q in r["quotes"]:
            quotes[q["supplier"]] = Quote.objects.create(
                request=req, supplier=suppliers[q["supplier"]],
                unit_price_rial=Decimal(q["unit_price_rial"]), quoted_on=_d(q["quoted_on"]),
                is_selected=q["is_selected"], reason=reasons.get(q["reason"]),
                is_official=q["is_official"], vat_pct=Decimal(q["vat_pct"]), note=q["note"],
            )
        requests[r["key"]] = (req, quotes)

    for o in data["orders"]:
        on = _d(o["ordered_on"])
        req, quotes = requests.get(o["request"], (None, {}))
        PurchaseOrder.objects.create(
            order_no=number("PO", on), request=req, quote=quotes.get(o["supplier"]),
            supplier=suppliers[o["supplier"]], material=materials[o["material"]],
            quantity=Decimal(o["quantity"]), unit_price_rial=Decimal(o["unit_price_rial"]),
            ordered_on=on, delivered_on=_d(o["delivered_on"]), period=period(on),
            status=o["status"], payment_term=terms.get(o["payment_term"]),
            payment_method=o["payment_method"], payment_note=o["payment_note"],
            is_official=o["is_official"], vat_pct=Decimal(o["vat_pct"]),
            note=tagged(o["note"]),
        )

    for s in data["samples"]:
        on = _d(s["requested_on"])
        Sample.objects.create(
            sample_no=number("SM", on), supplier=suppliers[s["supplier"]],
            material=materials[s["material"]], quantity=Decimal(s["quantity"]),
            spec=s["spec"], requested_on=on, received_on=_d(s["received_on"]),
            decided_on=_d(s["decided_on"]), status=s["status"],
            reason=reasons.get(s["reason"]), lab_note=s["lab_note"],
            note=tagged(s["note"]),
        )


def unload(apps, schema_editor):
    tag = json.loads(DATA.read_text(encoding="utf-8"))["tag"]
    for name in ("PurchaseOrder", "Sample", "PurchaseRequest"):  # quotes cascade
        apps.get_model("commercial", name).objects.filter(note__contains=tag).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("commercial", "0011_unicode_codes"),
        ("core", "0009_period_grain"),
    ]

    operations = [migrations.RunPython(load, unload)]
