"""
«ورود مشتریان» — the customer lists exported from تیم‌یار.

Each workbook has a sheet per kind (حقیقی، حقوقی، sometimes «تکمیل نشده»),
two header rows (Persian, then تیم‌یار's own field names — read by the
latter, which do not move), and one customer per row.

The point is to land each row on the customer CRM *already* has, not beside
it. That is decided by codes, never by names:

1. «آخرین توضیحات» carries where the row came from — «منبع: آرپا کد 101003»
   or «منبع: دیدار کد 1132». That code is looked up in CRM's identity layer
   (`CustomerExternalRef`), the same one the آرپا and دیدار uploads use.
2. Otherwise a شناسه/کد ملی or کد اقتصادی equal to one already on file.
3. Otherwise it is a new customer — and the آرپا/دیدار code it carries is
   filed against it, so that source's next upload finds it.

A match only fills what the customer is missing: a phone or province a
salesperson typed is never overwritten. Rows tagged «تامین کننده» are
suppliers, not customers, and are left out. Nothing is guessed — a name
that merely looks like an existing customer is not a match.
"""
from __future__ import annotations

import hashlib
import io
import re
from collections import Counter, defaultdict

from django.db import transaction
from django.utils import timezone

from apps.crm.arpa_file import ArpaFileError
from apps.crm.channels import ChannelResolver
from apps.crm.matching import fold, id_key
from apps.crm.models import (
    Customer, CustomerExternalRef, CustomerGroup, Dataset, ExternalSource, ImportBatch,
)
from apps.crm.people import RepMatcher
from apps.sales.models import DimProvince, SalesChannel

#: تیم‌یار's own field names, the second header row. The column after
#: HOME_PHONE has none; it is «طبقه بندی».
FIELDS = (
    "ID", "NAME", "LAST_NAME", "NATIONAL_CODE", "TITLE", "TIN", "ACCOUNT", "KPP",
    "PHONE", "FAX", "EMAIL", "WEB", "COUNTRY", "STATE", "CITY", "ZIP", "ADDRESS",
    "NUMBER_PERSONNEL", "LABLE", "PROPERTY_CODE", "WORK_PHONE", "LAST_COMMENT",
    "HOME_PHONE", "CLASS",
)
SUPPLIER = "تامین کننده"
UNKNOWN = {"نامعلوم", "نامشخص", "-"}

ARPA_CODE = re.compile(r"آرپا\s*کد\s*(\d+)")
DIDAR_CODE = re.compile(r"دیدار\s*کد\s*(\d+)")
OWNER = re.compile(r"(?:بازاریاب|مسئول در دیدار)\s*:\s*([^|]+)")


class TeamyarFileError(ArpaFileError):
    """Not a تیم‌یار customer export."""


def _text(v) -> str:
    s = fold(v)
    return "" if s in UNKNOWN else s


def read_files(files: list[tuple[str, bytes]]) -> tuple[list[dict], list[dict]]:
    import openpyxl

    rows, found = [], []
    for name, data in files:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise TeamyarFileError(f"«{name}» فایل اکسل نیست.") from exc
        sheets = []
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            head = [fold(h) for h in next(it, ())]
            codes = [fold(h) for h in next(it, ())]
            if "شناسه" not in head[:1] or "NAME" not in codes:
                continue
            n = 0
            for r in it:
                if not any(v not in (None, "") for v in r):
                    continue
                row = {f: (r[i] if i < len(r) else None) for i, f in enumerate(FIELDS)}
                row["_sheet"], row["_file"] = ws.title.strip(), name
                rows.append(row)
                n += 1
            sheets.append({"sheet": ws.title.strip(), "rows": n})
        wb.close()
        if not sheets:
            raise TeamyarFileError(f"«{name}» خروجی مشتریان تیم‌یار نیست.")
        found.append({"file": name, "sheets": sheets})
    return rows, found


class Importer:
    def __init__(self):
        self.stats: Counter = Counter()
        self.matched_by: Counter = Counter()
        self.skipped: Counter = Counter()
        self.reps = RepMatcher()
        self.channels = ChannelResolver()
        self.refs: dict[tuple[str, str], int] = {
            (s, e): c for s, e, c in CustomerExternalRef.objects.values_list(
                "source", "external_id", "customer_id")
        }
        # An id is a match only if it names one customer. A bank's branches
        # share its شناسه ملی; matching on it would fold every branch in
        # every province into one account.
        owners: dict[str, set[int]] = defaultdict(set)
        for pk, nid, eco in Customer.objects.values_list("pk", "national_id", "economic_code"):
            for v in (id_key(nid), id_key(eco)):
                if v:
                    owners[v].add(pk)
        self.by_id = {v: next(iter(p)) for v, p in owners.items() if len(p) == 1}
        self.shared_in_file: set[str] = set()
        self.provinces = {
            re.sub(r"\s|و", "", fold(p.name_fa)): p for p in DimProvince.objects.all()
        }
        self.groups: dict[str, CustomerGroup] = {}
        self.seen: set[int] = set()

    def _link(self, source: str, external_id: str, customer: Customer, name: str):
        key = (source, external_id[:64])
        if key in self.refs:
            return
        CustomerExternalRef.objects.create(
            source=source, external_id=key[1], customer=customer,
            external_name=name[:200], dataset=Dataset.REAL,
        )
        self.refs[key] = customer.pk

    def _group(self, name: str):
        if not name:
            return None
        if name not in self.groups:
            from django.utils.text import slugify
            self.groups[name] = CustomerGroup.objects.get_or_create(
                code=f"cg-{slugify(name, allow_unicode=True)[:40]}",
                defaults={"name_fa": name[:100]},
            )[0]
        return self.groups[name]

    def row(self, r: dict):
        name = re.sub(r"\s+", " ", f"{_text(r['NAME'])} {_text(r['LAST_NAME'])}").strip()
        if not name:
            self.skipped["بدون نام"] += 1
            return
        if _text(r["LABLE"]) == SUPPLIER:
            self.skipped["تامین‌کننده است، نه مشتری"] += 1
            return

        person = _text(r["ACCOUNT"]) == "حقیقی"
        comment = _text(r["LAST_COMMENT"])
        arpa = (ARPA_CODE.search(comment) or [None, None])[1]
        didar = (DIDAR_CODE.search(comment) or [None, None])[1]
        tid = _text(r["ID"])
        nid = id_key(r["NATIONAL_CODE"])
        eco = id_key(r["TIN"])
        own = OWNER.search(comment)
        owner = self.reps.match(own[1].strip()) if own else None

        # 1. the code it came from, 2. an exact id, 3. its own earlier upload.
        pk, how = None, ""
        if arpa and (ExternalSource.ARPA, arpa) in self.refs:
            pk, how = self.refs[(ExternalSource.ARPA, arpa)], "کد آرپا"
        if not pk and didar:
            for ref in ((f"pe-{didar}", f"co-{didar}") if person else (f"co-{didar}", f"pe-{didar}")):
                if (ExternalSource.DIDAR, ref) in self.refs:
                    pk, how = self.refs[(ExternalSource.DIDAR, ref)], "کد دیدار"
                    break
        if not pk:
            for v in (nid, eco):
                if v and v in self.by_id and v not in self.shared_in_file:
                    pk, how = self.by_id[v], "شناسه/کد ملی"
                    break
        team_key = tid or "n-" + hashlib.sha256(name.encode()).hexdigest()[:24]
        if not pk and (ExternalSource.TEAMYAR, team_key) in self.refs:
            pk, how = self.refs[(ExternalSource.TEAMYAR, team_key)], "ورود قبلی تیم‌یار"

        cls = _text(r["CLASS"])
        province = self.provinces.get(re.sub(r"\s|و", "", _text(r["STATE"]))) if _text(r["STATE"]) else None
        fields = {
            "national_id": nid,
            "economic_code": eco,
            "mobile": _text(r["PHONE"])[:40],
            "phone": (_text(r["WORK_PHONE"]) or _text(r["HOME_PHONE"]))[:40],
            "email": _text(r["EMAIL"])[:254] if "@" in _text(r["EMAIL"]) else "",
            "postal_code": re.sub(r"\D", "", _text(r["ZIP"]))[:10],
            "address": _text(r["ADDRESS"])[:400],
            "city": _text(r["CITY"])[:100],
            "province": province,
            "contact_name": "" if person else _text(r["TITLE"])[:150],
            "group": self._group(cls),
            "owner": owner,
        }

        if pk:
            if pk in self.seen:
                self.stats["duplicate"] += 1  # the same customer twice in these files
            customer = Customer.objects.get(pk=pk)
            changed = [f for f, v in fields.items() if v and not getattr(customer, f)]
            for f in changed:
                setattr(customer, f, fields[f])
            if changed:
                customer.save(update_fields=changed)
                self.stats["updated"] += 1
            else:
                self.stats["unchanged"] += 1
            self.matched_by[how] += 1
        else:
            channel = (
                SalesChannel.B2B if cls == "B2B"
                else self.channels.customer(owner.pk if owner else None, None)
            )
            customer = Customer.objects.create(
                code=f"teamyar-{team_key}"[:50], name_fa=name[:200], dataset=Dataset.REAL,
                kind=Customer.Kind.PERSON if person else Customer.Kind.COMPANY,
                status=Customer.Status.LEAD, channel=channel,
                first_contact_at=timezone.now(),
                **{k: v for k, v in fields.items() if v},
            )
            self.stats["created"] += 1
        self.seen.add(customer.pk)

        # File every code the row carries, so each source's next upload
        # finds this customer instead of making another.
        self._link(ExternalSource.TEAMYAR, team_key, customer, name)
        if arpa:
            self._link(ExternalSource.ARPA, arpa, customer, name)
        if didar and not any((ExternalSource.DIDAR, f"{p}-{didar}") in self.refs for p in ("pe", "co")):
            self._link(ExternalSource.DIDAR, f"{'pe' if person else 'co'}-{didar}", customer, name)


def run(files: list[tuple[str, bytes]], user=None, commit: bool = False) -> dict:
    rows, found = read_files(files)
    sha = hashlib.sha256(b"".join(hashlib.sha256(d).digest() for _, d in sorted(files))).hexdigest()
    previous = ImportBatch.objects.filter(source=ImportBatch.Source.TEAMYAR, file_sha256=sha).first()
    imp = Importer()
    ids = Counter(v for r in rows for v in {id_key(r["NATIONAL_CODE"]), id_key(r["TIN"])} if v)
    imp.shared_in_file = {v for v, n in ids.items() if n > 1}
    with transaction.atomic():
        for r in rows:
            imp.row(r)
        s = imp.stats
        batch = ImportBatch.objects.create(
            source=ImportBatch.Source.TEAMYAR, book="",
            file_name="، ".join(f["file"] for f in found)[:255], file_sha256=sha,
            uploaded_by=user, rows=len(rows), created=s["created"], updated=s["updated"],
            unchanged=s["unchanged"], skipped=sum(imp.skipped.values()),
            customers_created=s["created"],
            notes={"matched_by": dict(imp.matched_by), "skipped": dict(imp.skipped),
                   "unknown_reps": dict(imp.reps.unknown.most_common(30))},
        )
        if not commit:
            transaction.set_rollback(True)
    return {
        "files": found,
        "rows": len(rows),
        "created": s["created"],
        "updated": s["updated"],
        "unchanged": s["unchanged"],
        "duplicate": s["duplicate"],
        "matched_by": dict(imp.matched_by),
        "skipped": dict(imp.skipped),
        "unknown_reps": [{"name": n, "count": c} for n, c in imp.reps.unknown.most_common()],
        "nothing_new": not s["created"] and not s["updated"],
        "committed": commit,
        "batch_id": batch.pk if commit else None,
        "previous": (
            {"at": previous.created_at.isoformat(), "by": getattr(previous.uploaded_by, "username", "")}
            if previous else None
        ),
    }
