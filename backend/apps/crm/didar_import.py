"""
«ورود از دیدار» — دیدار's exports, uploaded from the site.

دیدار is where the sales team's *relationship* history lives: people and
companies, the deals still open and the ones lost, the calls and meetings,
the notes. It is **not** where sales are: those are آرپا's invoices, and each
invoice is its own won deal (`apps.crm.arpa_import`). So nothing here writes
a SalesInvoice, and a deal دیدار marks won is not taken.

The files are told apart by what is in them, not by their names, because the
names do not say: every دیدار export carries a `_type` column («Company»,
«Contact», «Deal», «Product», «Activity», «Note», «Case»), and «کارت ها.xlsx»
turned out to hold the product list. Any subset can be uploaded together;
they are applied in dependency order — products, companies, people, deals,
activities and notes, cards.

What makes a re-upload safe:

* Customers and deals have دیدار ids and are keyed on them. A customer that
  already exists is only *filled in* — a phone, an address, a province a
  salesperson typed by hand is never overwritten — and a دیدار company whose
  شناسه ملی matches an account already in the CRM (say, from آرپا) is that
  account, not a second one.
* Activities have no id in دیدار at all, so each gets one here: who, what
  kind, when it was planned, and with whom. Both «فعالیت ها» and «یاداشت ها»
  carry the same 9,403 activities; the key is what stops them landing twice.
  A planned call that has since been done turns from a کار into an activity.
* A salesperson's name that is not on the roster leaves the owner blank and
  is reported. Nothing is guessed — no employee is invented, no province
  read off an address.
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import re
from collections import Counter, defaultdict
from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core import jalali

from apps.crm.arpa_file import ArpaFileError
from apps.crm.channels import ChannelResolver
from apps.crm.jalali import period_for
from apps.crm.matching import fold, id_key
from apps.crm.people import RepMatcher
from apps.crm.models import (
    Activity, Customer, CustomerExternalRef, Dataset, Deal, DealItem, ExternalSource,
    ImportBatch, LeadSource, LostReason, PipelineStage, Product, ProductCategory, Task,
)
from apps.sales.models import DimEmployee, DimProvince

#: `_type` → our name for the sheet, in the order they must be applied.
KINDS = {
    "Product": "products",
    "Company": "companies",
    "Contact": "contacts",
    "Deal": "deals",
    "Activity": "activities",
    "Note": "notes",
    "Case": "cases",
}
ORDER = list(KINDS.values())

STATUS = {"موفق": "won", "ناموفق": "lost", "جاری": "open"}

#: دیدار's activity types onto ours. Anything unrecognised becomes a call —
#: the department's own vocabulary is overwhelmingly «تماس پیگیری».
ACTIVITY_KIND = {
    "تماس پیگیری": "call_out",
    "تماس خروجی": "call_out",
    "تماس ورودی": "call_in",
    "اعلام قیمت": "quote",
    "ارسال نمونه": "sample",
    "جلسه حضوری": "meeting",
    "ارسال پیام": "message",
    "ثبت سفارش": "order",
    "صدور فاکتور": "invoice",
    "پرداخت": "payment",
}
RESULT = {"انجام شده": "success", "انجام نشده": "no_answer"}
UNIT = {"رول": "roll", "برگ": "sheet", "بسته": "pack", "تن": "ton"}


def norm(value) -> str:
    """Trim and fold the whitespace دیدار leaves around almost every name."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fit(model, field: str, value) -> str:
    """
    Clamp a value to its column's width, read from the model.

    SQLite ignores `VARCHAR(n)`, so an over-long value writes clean here and
    PostgreSQL on the server stops on «value too long». Asking the model
    rather than writing the number at each call site is what keeps it right.
    """
    limit = model._meta.get_field(field).max_length
    text = "" if value is None else str(value)
    return text[:limit] if limit else text


def plain(value) -> str:
    """
    دیدار's rich-text note bodies as text: «<p>…&nbsp;</p>» arrives for
    «تماس گرفتم». Rendered as HTML it would be an injection point — this is
    other people's typing — so tags out, entities decoded, spaces folded.
    """
    text = re.sub(r"<br\s*/?>|</p>|</div>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def jdate(value):
    """«1405/03/13» → a date; None for blanks and anything odd."""
    parts = re.split(r"[/\-]", norm(value))
    if len(parts) != 3:
        return None
    try:
        y, m, d = (int(p) for p in parts)
        return jalali.to_gregorian(y, m, d) if y > 1000 else None
    except (ValueError, TypeError):
        return None


def jaware(value):
    """Same, as an aware datetime at 09:00."""
    day = jdate(value)
    return timezone.make_aware(datetime.combine(day, time(9, 0))) if day else None


def dec(value) -> Decimal:
    text = re.sub(r"[^\d.\-]", "", str(value or "0"))
    try:
        return Decimal(text or "0")
    except InvalidOperation:
        return Decimal(0)


def code_for(prefix: str, value, fallback: str = "") -> str:
    """A stable slug from a دیدار id, or from a name when there is no id."""
    raw = norm(value)
    if raw and raw not in {"0", "None"}:
        return f"{prefix}-{slugify(raw, allow_unicode=False) or raw}"
    return f"{prefix}-{slugify(norm(fallback), allow_unicode=True)[:40] or 'x'}"


LABELS = {
    "products": "محصول", "companies": "شرکت", "contacts": "شخص", "deals": "معامله‌ی جاری و ناموفق",
    "activities": "فعالیت", "notes": "یادداشت", "cases": "کارت",
}


class DidarFileError(ArpaFileError):
    """Not a دیدار export."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def read_files(files: list[tuple[str, bytes]]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Every sheet of every file, sorted by what it holds."""
    import openpyxl

    sheets: dict[str, list[dict]] = defaultdict(list)
    found: list[dict] = []
    for name, data in files:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise DidarFileError(f"«{name}» فایل اکسل نیست.") from exc
        kinds = []
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = [norm(h) for h in next(rows, ())]
            if not header or header[0] != "_type":
                continue
            data_rows = [dict(zip(header, r)) for r in rows if any(v not in (None, "") for v in r)]
            if not data_rows:
                continue
            kind = KINDS.get(norm(data_rows[0].get("_type")))
            if kind:
                sheets[kind].extend(data_rows)
                kinds.append({"kind": kind, "label": LABELS[kind], "rows": len(data_rows)})
        wb.close()
        if not kinds:
            raise DidarFileError(f"«{name}» خروجی دیدار نیست (ستون _type ندارد).")
        found.append({"file": name, "sheets": kinds})
    return sheets, found


def _first(value) -> str:
    """دیدار lists several people as «12, 34»; the first is the one we keep."""
    return norm(str(value or "").replace("،", ",").split(",")[0])


def _at(day, clock) -> datetime | None:
    """A Jalali date and «09:54» as one aware timestamp."""
    d = jdate(day)
    if not d:
        return None
    h, m = 9, 0
    match = re.search(r"(\d{1,2}):(\d{2})", str(clock or ""))
    if match:
        h, m = min(int(match[1]), 23), min(int(match[2]), 59)
    return timezone.make_aware(datetime(d.year, d.month, d.day, h, m))


def _key(*parts) -> str:
    return hashlib.sha256("|".join(norm(p) for p in parts).encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
class Importer:
    def __init__(self):
        self.stats: dict[str, Counter] = defaultdict(Counter)
        self.skipped: dict[str, Counter] = defaultdict(Counter)
        self.reps = RepMatcher()
        self.provinces = {
            re.sub(r"\s|و", "", fold(p.name_fa)): p for p in DimProvince.objects.all()
        }
        # «co-123» / «pe-456» → customer id: every دیدار id the CRM knows.
        self.refs: dict[str, int] = dict(
            CustomerExternalRef.objects.filter(source=ExternalSource.DIDAR)
            .values_list("external_id", "customer_id")
        )
        self.by_national_id = {
            id_key(n): pk for pk, n in Customer.objects.exclude(national_id="")
            .values_list("pk", "national_id") if id_key(n)
        }
        self.channels = ChannelResolver()
        self._periods: dict = {}
        self.touched: set[int] = set()
        self.created_customers: set[int] = set()

    def period(self, when):
        """`period_for`, once per month rather than once per row — the upload
        has ten thousand rows and only a few dozen months."""
        from apps.crm.jalali import jalali_month_of

        month = jalali_month_of(when)
        if month not in self._periods:
            self._periods[month] = period_for(when)
        return self._periods[month]

    # -- people ---------------------------------------------------------------
    def rep(self, name) -> DimEmployee | None:
        """The roster's colleague for a دیدار name, or nobody — never a new one."""
        return self.reps.match(name)

    def province(self, name):
        """Only a province دیدار names outright; otherwise blank."""
        return self.provinces.get(re.sub(r"\s|و", "", fold(name))) if norm(name) else None

    # -- customers ------------------------------------------------------------
    def _link(self, ref: str, customer: Customer, name: str) -> None:
        CustomerExternalRef.objects.update_or_create(
            source=ExternalSource.DIDAR, external_id=ref[:64],
            defaults={"customer": customer, "external_name": name[:200]},
        )
        self.refs[ref] = customer.pk

    def _upsert_customer(self, kind: str, ref: str, name: str, fields: dict, nid: str) -> Customer:
        """New: everything. Existing: only the blanks — people edit these by hand."""
        pk = self.refs.get(ref) or (self.by_national_id.get(nid) if nid else None)
        if pk:
            customer = Customer.objects.get(pk=pk)
            changed = [
                f for f, v in fields.items()
                if v not in (None, "") and not getattr(customer, f)
            ]
            for f in changed:
                setattr(customer, f, fields[f])
            if changed:
                customer.save(update_fields=changed)
                self.stats[kind]["updated"] += 1
            else:
                self.stats[kind]["unchanged"] += 1
            if ref not in self.refs:
                self._link(ref, customer, name)
        else:
            owner = fields.get("owner")
            # The owner's roster says which department; no owner, the default.
            fields["channel"] = self.channels.customer(owner.pk if owner else None, None)
            customer = Customer.objects.create(
                code=f"didar-{ref}"[:50], name_fa=name[:200], dataset=Dataset.REAL,
                **{k: v for k, v in fields.items() if v not in (None, "")},
            )
            self._link(ref, customer, name)
            self.created_customers.add(customer.pk)
            if nid:
                self.by_national_id[nid] = customer.pk
            self.stats[kind]["created"] += 1
        self.touched.add(customer.pk)
        return customer

    def companies(self, rows):
        for row in rows:
            did, name = norm(row.get("کد دیدار شرکت")), norm(row.get("نام شرکت"))
            if not did or not name:
                self.skipped["companies"]["بدون کد یا نام"] += 1
                continue
            nid = id_key(row.get("شناسه ملی"))
            self._upsert_customer("companies", f"co-{did}", name, {
                "kind": Customer.Kind.COMPANY,
                "phone": fit(Customer, "phone", norm(row.get("تلفن شرکت"))),
                "email": fit(Customer, "email", norm(row.get("ایمیل شرکت"))),
                "address": fit(Customer, "address", norm(row.get("آدرس"))),
                "national_id": fit(Customer, "national_id", nid),
                "economic_code": fit(Customer, "economic_code", id_key(row.get("شماره اقتصادی"))),
                "registration_no": fit(Customer, "registration_no", norm(row.get("شماره ثبت"))),
                "postal_code": fit(Customer, "postal_code", norm(row.get("کد پستی"))),
                "city": fit(Customer, "city", norm(row.get("شهرستان"))),
                "province": self.province(row.get("استان (فیلد پیش فرض)") or row.get("استان_1")),
                "owner": self.rep(row.get("مسئول شرکت")),
                "note": fit(Customer, "note", plain(row.get("توضیحات شرکت"))),
                "first_contact_at": jaware(row.get("تاریخ ثبت شرکت")) or timezone.now(),
            }, nid)

    def contacts(self, rows):
        for row in rows:
            did = norm(row.get("کد دیدار مشتری"))
            full = norm(f"{row.get('نام مشتری') or ''} {row.get('نام خانوادگی مشتری') or ''}")
            if not did or not full:
                self.skipped["contacts"]["بدون کد یا نام"] += 1
                continue
            company = norm(row.get("کد دیدار شرکت"))
            parent_pk = self.refs.get(f"co-{company}") if company not in ("", "0") else None
            mobile = fit(Customer, "mobile", norm(row.get("تلفن همراه مشتری")))
            if parent_pk:
                # A person at a company is how you reach that company — its
                # contact, not a customer of their own.
                parent = Customer.objects.get(pk=parent_pk)
                if not parent.contact_name:
                    parent.contact_name = fit(Customer, "contact_name", full)
                    parent.mobile = parent.mobile or mobile
                    parent.save(update_fields=["contact_name", "mobile"])
                if f"pe-{did}" not in self.refs:
                    self._link(f"pe-{did}", parent, full)
                self.stats["contacts"]["merged"] += 1
                continue
            nid = id_key(row.get("کد ملی مشتری"))
            self._upsert_customer("contacts", f"pe-{did}", full, {
                "kind": Customer.Kind.PERSON,
                "contact_name": fit(Customer, "contact_name", full),
                "mobile": mobile,
                "phone": fit(Customer, "phone", norm(row.get("تلفن ثابت مشتری"))),
                "email": fit(Customer, "email", norm(row.get("ایمیل مشتری"))),
                "national_id": fit(Customer, "national_id", nid),
                "postal_code": fit(Customer, "postal_code", norm(row.get("کد پستی"))),
                "address": fit(Customer, "address", norm(row.get("آدرس"))),
                "city": fit(Customer, "city", norm(row.get("شهرستان"))),
                "province": self.province(row.get("استان (فیلد پیش فرض)")),
                "owner": self.rep(row.get("مسئول مشتری")),
                "note": fit(Customer, "note", plain(row.get("توضیحات شخص"))),
                "first_contact_at": jaware(row.get("تاریخ ثبت مشتری")) or timezone.now(),
            }, nid)

    def customer_for(self, person, company) -> Customer | None:
        for ref in (f"pe-{_first(person)}", f"co-{_first(company)}"):
            pk = self.refs.get(ref)
            if pk and not ref.endswith("-") and not ref.endswith("-0"):
                self.touched.add(pk)
                return Customer(pk=pk)
        return None

    # -- products & deals -----------------------------------------------------
    def products(self, rows):
        cats: dict[str, ProductCategory] = {}
        seen = set()
        for row in rows:
            key = norm(row.get("کد محصول")) or norm(row.get("کد دیدار محصول"))
            title = norm(row.get("عنوان محصول"))
            if not key or not title or key in seen:
                continue
            seen.add(key)
            group = norm(row.get("گروه محصول")) or "بدون گروه"
            if group not in cats:
                cats[group] = ProductCategory.objects.get_or_create(
                    code=code_for("pc", "", group), defaults={"name_fa": group[:100]},
                )[0]
            values = {
                "name_fa": title[:150], "category_id": cats[group].pk,
                "unit": UNIT.get(norm(row.get("واحد محصول")), "roll"),
                "list_price_rial": dec(row.get("قیمت هر واحد محصول")),
                "is_active": norm(row.get("فعال/غیر فعال")) != "غیر فعال",
            }
            self._sync(Product, "products", {"code": code_for("pr", key)}, values)

    def _sync(self, model, kind: str, lookup: dict, values: dict) -> None:
        """Create, update, or — when nothing differs — leave alone and say so."""
        obj = model.objects.filter(**lookup).first()
        if obj is None:
            model.objects.create(**lookup, **values)
            self.stats[kind]["created"] += 1
        elif any(getattr(obj, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(obj, k, v)
            obj.save()
            self.stats[kind]["updated"] += 1
        else:
            self.stats[kind]["unchanged"] += 1

    def _named(self, model, prefix, name, **extra):
        if not name:
            return None
        return model.objects.get_or_create(
            code=code_for(prefix, "", name), defaults={"name_fa": name[:120], **extra},
        )[0]

    def deals(self, rows):
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            did = norm(row.get("کد دیدار معامله"))
            if did:
                grouped[did].append(row)
        n_stages = PipelineStage.objects.count()
        products = {p.code: p for p in Product.objects.all()}
        for did, lines in grouped.items():
            head = lines[0]
            if STATUS.get(norm(head.get("وضعیت معامله"))) == "won":
                # A won deal is an آرپا invoice (`arpa_import.sync_deal`);
                # taking دیدار's too would count every sale twice. One that
                # was still open when it came in earlier leaves the pipeline.
                Deal.objects.filter(code=code_for("didar-d", did)).delete()
                self.skipped["deals"]["موفق — از فاکتور آرپا می‌آید"] += 1
                continue
            customer = self.customer_for(head.get("کد دیدار شخص معامله"), head.get("کد دیدار شرکت معامله"))
            if not customer:
                self.skipped["deals"]["مشتری‌اش در CRM نیست"] += 1
                continue
            stage_name = norm(head.get("مرحله کاریز معامله"))
            stage = None
            if stage_name:
                stage = PipelineStage.objects.filter(code=code_for("st", "", stage_name)).first()
                if not stage:
                    n_stages += 1
                    stage = PipelineStage.objects.create(
                        code=code_for("st", "", stage_name), name_fa=stage_name[:120],
                        order=n_stages, kind=PipelineStage.Kind.OPEN,
                    )
            opened = jaware(head.get("تاریخ ایجاد معامله")) or timezone.now()
            closed = jaware(head.get("تاریخ انجام معامله"))
            values = {
                "title": fit(Deal, "title", norm(head.get("عنوان معامله")) or f"معامله {did}"),
                "customer_id": customer.pk,
                "owner": self.rep(head.get("مسئول معامله")),
                "stage": stage,
                "status": STATUS.get(norm(head.get("وضعیت معامله")), "open"),
                "lead_source": self._named(LeadSource, "ls", norm(head.get("شیوه آشنایی معامله"))),
                "lost_reason": self._named(LostReason, "lr", norm(head.get("دلیل شکست معامله"))),
                "lost_note": fit(Deal, "lost_note", plain(head.get("یادداشت شکست معامله"))),
                # Straight from دیدار: a third of the deals have no line items.
                "amount_rial": dec(head.get("ارزش معامله")),
                "opened_at": opened,
                "closed_at": closed,
                "period": self.period(opened),
                "close_period": self.period(closed) if closed else None,
                "expected_close_date": jdate(head.get("تاریخ احتمالی انجام معامله")),
                "dataset": Dataset.REAL,
            }
            code = code_for("didar-d", did)
            deal = Deal.objects.filter(code=code).first()
            if deal and all(
                getattr(deal, k if not hasattr(v, "pk") else f"{k}_id") == (v.pk if hasattr(v, "pk") else v)
                for k, v in values.items() if k not in ("period", "close_period")
            ):
                self.stats["deals"]["unchanged"] += 1
                continue
            if deal:
                for k, v in values.items():
                    setattr(deal, k, v)
                deal.save()
                self.stats["deals"]["updated"] += 1
            else:
                deal = Deal.objects.create(code=code, **values)
                self.stats["deals"]["created"] += 1
            deal.items.all().delete()
            for line in lines:
                title = norm(line.get("عنوان محصول"))
                if not title:
                    continue
                DealItem.objects.create(
                    deal=deal, product=products.get(code_for("pr", norm(line.get("کد محصول")))),
                    quantity=dec(line.get("تعداد محصول")) or Decimal(1),
                    unit_price_rial=dec(line.get("قیمت")), dataset=Dataset.REAL,
                )

    # -- activities, notes, cards ---------------------------------------------
    def activities(self, rows, notes):
        deals = dict(Deal.objects.filter(code__startswith="didar-d-").values_list("code", "pk"))
        acts = {
            k: (pk, owner) for k, pk, owner in Activity.objects.exclude(external_key="")
            .values_list("external_key", "pk", "owner_id")
        }
        tasks = dict(Task.objects.exclude(external_key="").values_list("external_key", "pk"))
        new_acts, new_tasks, done_tasks, seen, seen_done = [], [], [], set(), set()
        owners: dict[int, int] = {}

        def one(kind_label, row, key, plan_key, title, text, owner_name, planned, at, done):
            """
            `key` names a done activity — down to when it was done and what
            was written — so two calls to one person in one planned slot stay
            two. `plan_key` names the slot alone: it is the identity of a
            not-yet-done کار, and how that کار is found again once it is done.
            """
            if not done:
                key = plan_key
            if key in seen:
                self.stats[kind_label]["unchanged"] += 1
                return
            seen.add(key)
            customer = self.customer_for(row.get("کد اشخاص فعالیت") or row.get("کد اشخاص یادداشت"),
                                         row.get("کد شرکت های فعالیت") or row.get("کد شرکت های یادداشت"))
            if not customer:
                self.skipped[kind_label]["مشتری‌اش در CRM نیست"] += 1
                return
            if not (at or planned):
                self.skipped[kind_label]["بدون تاریخ"] += 1
                return
            owner = self.rep(owner_name)
            if key in acts:
                pk, had = acts[key]
                if owner and not had:
                    owners[pk] = owner.pk  # added to the roster since
                    self.stats[kind_label]["updated"] += 1
                else:
                    self.stats[kind_label]["unchanged"] += 1
                return
            if key in tasks and not done:
                self.stats[kind_label]["unchanged"] += 1
                return
            kind = ACTIVITY_KIND.get(norm(row.get("نوع فعالیت")), "message" if kind_label == "notes" else "call_out")
            deal_pk = deals.get(code_for("didar-d", _first(row.get("کد معامله فعالیت") or row.get("کد معامله یادداشت"))))
            if done:
                if plan_key in tasks and plan_key not in seen_done:
                    seen_done.add(plan_key)
                    done_tasks.append(tasks[plan_key])  # planned then, done since
                    self.stats[kind_label]["updated"] += 1
                else:
                    self.stats[kind_label]["created"] += 1
                when = at or planned
                new_acts.append(Activity(
                    kind=kind, customer_id=customer.pk, deal_id=deal_pk, owner=owner, at=when,
                    result=RESULT.get(norm(row.get("وضعیت اجرای فعالیت")), "success"),
                    note=fit(Activity, "note", text), period=self.period(when),
                    external_key=key, dataset=Dataset.REAL,
                ))
            else:
                self.stats[kind_label]["created"] += 1
                new_tasks.append(Task(
                    title=fit(Task, "title", title or "پیگیری"), customer_id=customer.pk,
                    deal_id=deal_pk, owner=owner, kind=kind, due_at=planned or at,
                    note=fit(Task, "note", text), external_key=key, dataset=Dataset.REAL,
                ))

        for row in rows:
            type_ = norm(row.get("نوع فعالیت"))
            title = plain(row.get("عنوان فعالیت"))
            body = plain(row.get("متن فعالیت"))
            planned = _at(row.get("تاریخ برنامه ریزی شده اجرا فعالیت"), row.get("زمان برنامه ریزی شده اجرا فعالیت"))
            at = _at(row.get("تاریخ انجام شدن فعالیت"), row.get("زمان انجام شدن فعالیت"))
            plan_key = _key("act", type_, title, row.get("مسئول اجرا فعالیت"), row.get("ثبت کننده فعالیت"),
                            row.get("تاریخ برنامه ریزی شده اجرا فعالیت"), row.get("زمان برنامه ریزی شده اجرا فعالیت"),
                            _first(row.get("کد اشخاص فعالیت")), _first(row.get("کد شرکت های فعالیت")),
                            _first(row.get("کد معامله فعالیت")))
            key = _key(plan_key, row.get("تاریخ انجام شدن فعالیت"), row.get("زمان انجام شدن فعالیت"), body)
            one("activities", row, key, plan_key, title,
                body or (title if title != type_ else ""), row.get("مسئول اجرا فعالیت"),
                planned, at, norm(row.get("وضعیت اجرای فعالیت")) != "انجام نشده")

        for row in notes:
            text = plain(row.get("یادداشت"))
            when = _at(row.get("تاریخ برنامه ریزی یادداشت"), row.get("زمان برنامه ریزی یادداشت"))
            key = _key("note", row.get("ثبت کننده یادداشت"), row.get("تاریخ برنامه ریزی یادداشت"),
                       row.get("زمان برنامه ریزی یادداشت"), _first(row.get("کد اشخاص یادداشت")),
                       _first(row.get("کد شرکت های یادداشت")), _first(row.get("کد معامله یادداشت")), text)
            one("notes", row, key, key, "", text, row.get("ثبت کننده یادداشت"), when, when, True)

        if done_tasks:
            Task.objects.filter(pk__in=done_tasks).delete()
        for pk, owner_id in owners.items():
            Activity.objects.filter(pk=pk, owner__isnull=True).update(owner_id=owner_id)
        Activity.objects.bulk_create(new_acts, batch_size=500)
        Task.objects.bulk_create(new_tasks, batch_size=500)

    def cases(self, rows):
        for row in rows:
            did = norm(row.get("کد دیدار کارت"))
            title = plain(row.get("عنوان کارت"))
            customer = self.customer_for(row.get("کد دیدار شخص"), "")
            at = jaware(row.get("تاریخ انجام کارت")) or jaware(row.get("تاریخ ثبت کارت"))
            if not customer or not at or not title:
                self.skipped["cases"]["مشتری یا تاریخ ندارد"] += 1
                continue
            done = at if norm(row.get("وضعیت کارت")) not in ("", "باز") else None
            owner = self.rep(row.get("مسئول کارت"))
            self._sync(Task, "cases", {"external_key": f"didar-case-{did}"}, {
                "title": fit(Task, "title", title), "customer_id": customer.pk,
                "owner_id": owner.pk if owner else None, "due_at": at, "done_at": done,
                "note": fit(Task, "note", plain(row.get("توضیحات کارت"))),
                "dataset": Dataset.REAL,
            })

    # -- the facts about customers that follow from the rest -------------------
    def rollup(self):
        from django.db.models import Max, Min

        ids = self.touched
        if not ids:
            return
        last = dict(Activity.objects.filter(customer_id__in=ids).values("customer_id")
                    .annotate(m=Max("at")).values_list("customer_id", "m"))
        won = dict(Deal.objects.filter(customer_id__in=ids, status="won", closed_at__isnull=False)
                   .values("customer_id").annotate(m=Min("closed_at")).values_list("customer_id", "m"))
        batch = []
        for c in Customer.objects.filter(pk__in=ids):
            c.last_activity_at = max(filter(None, [c.last_activity_at, last.get(c.pk)]), default=None)
            c.first_deal_won_at = min(filter(None, [c.first_deal_won_at, won.get(c.pk)]), default=None)
            # A status is a person's call once the account exists; only a
            # customer this upload created gets one from its deals.
            if c.pk in self.created_customers and c.first_deal_won_at:
                c.status = Customer.Status.ACTIVE
            batch.append(c)
        Customer.objects.bulk_update(batch, ["last_activity_at", "first_deal_won_at", "status"], batch_size=500)


def run(files: list[tuple[str, bytes]], user=None, commit: bool = False) -> dict:
    """Preview (rolled back) or import; the same work either way."""
    sheets, found = read_files(files)
    sha = hashlib.sha256(b"".join(hashlib.sha256(d).digest() for _, d in sorted(files))).hexdigest()
    previous = ImportBatch.objects.filter(source=ImportBatch.Source.DIDAR, file_sha256=sha).first()

    imp = Importer()
    with transaction.atomic():
        if sheets.get("products"):
            imp.products(sheets["products"])
        imp.companies(sheets.get("companies", []))
        imp.contacts(sheets.get("contacts", []))
        if sheets.get("deals"):
            imp.deals(sheets["deals"])
        if sheets.get("activities") or sheets.get("notes"):
            imp.activities(sheets.get("activities", []), sheets.get("notes", []))
        if sheets.get("cases"):
            imp.cases(sheets["cases"])
        imp.rollup()

        per_kind = {
            k: {
                "label": LABELS[k],
                "rows": len(sheets.get(k, [])),
                "created": imp.stats[k]["created"],
                "updated": imp.stats[k]["updated"],
                "unchanged": imp.stats[k]["unchanged"],
                "merged": imp.stats[k]["merged"],
                "skipped": dict(imp.skipped[k]),
            }
            for k in ORDER if sheets.get(k)
        }
        created = sum(v["created"] for v in per_kind.values())
        updated = sum(v["updated"] for v in per_kind.values())
        batch = ImportBatch.objects.create(
            source=ImportBatch.Source.DIDAR,
            file_name="، ".join(f["file"] for f in found)[:255], file_sha256=sha,
            book="", uploaded_by=user,
            rows=sum(v["rows"] for v in per_kind.values()),
            created=created, updated=updated,
            unchanged=sum(v["unchanged"] for v in per_kind.values()),
            skipped=sum(sum(v["skipped"].values()) for v in per_kind.values()),
            customers_created=len(imp.created_customers),
            notes={"kinds": per_kind, "unknown_reps": dict(imp.reps.unknown.most_common(30))},
        )
        if not commit:
            transaction.set_rollback(True)

    return {
        "files": found,
        "kinds": per_kind,
        "created": created,
        "updated": updated,
        "customers_created": len(imp.created_customers),
        "unknown_reps": [{"name": n, "count": c} for n, c in imp.reps.unknown.most_common()],
        "nothing_new": not created and not updated,
        "committed": commit,
        "batch_id": batch.pk if commit else None,
        "previous": (
            {"at": previous.created_at.isoformat(), "by": getattr(previous.uploaded_by, "username", "")}
            if previous else None
        ),
    }
