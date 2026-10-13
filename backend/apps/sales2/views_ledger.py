"""
مطالبات طبق دفتر آرپا — API.

    ledger/receivables/            the collections report (one book, or both)
    ledger/receivables/export/     the same as «گزارش وصولی».xlsx
    ledger/preview/                read a «دفتر حساب» file, write nothing
    ledger/import/                 replace a customer's ledger in a book
    ledger/collections-import/     notes, marketers and figures from finance's workbook
    ledger/accounts/<id>/          one account settled: فاکتورها, دریافت‌ها, rows, checks
    ledger/customers/<id>/export/  one customer, both books, as a workbook
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.crm.models import Customer
from apps.sales2 import ledger
from apps.sales2.models import LedgerAccount, LedgerBook
from apps.sales2.permissions import Sales2Access

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BOOKS = (LedgerBook.MAIN, LedgerBook.SECOND)


def _book(raw, allow_all=False) -> str:
    raw = (raw or LedgerBook.MAIN).strip()
    if raw in BOOKS or (allow_all and raw == "all"):
        return raw
    raise ValidationError({"book": "دفتر نامعتبر است."})


def _as_of(request) -> date:
    raw = request.query_params.get("as_of")
    if not raw:
        return timezone.localdate()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise ValidationError({"as_of": "تاریخ نامعتبر است."})


def _months(request) -> int:
    try:
        return max(1, min(24, int(request.query_params.get("months") or 11)))
    except ValueError:
        return 11


def _s(v) -> str | None:
    return None if v is None else str(int(v))


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _row_json(r: dict) -> dict:
    return {
        **{k: r[k] for k in ("id", "customer", "name", "book", "code", "codes", "accounts", "note",
                             "marketer", "entries", "open_items", "issues", "reconciled", "has_ledger")},
        "buckets": {k: _s(v) for k, v in r["buckets"].items()},
        "by_book": {k: _s(v) for k, v in r["by_book"].items()},
        "prepayment": _s(r["prepayment"]), "balance": _s(r["balance"]),
        "file_balance": _s(r["file_balance"]) if r["has_ledger"] else None,
        "manual_balance": _s(r["manual_balance"]), "manual_as_of": _iso(r["manual_as_of"]),
        "oldest_open": _iso(r["oldest_open"]), "last_date": _iso(r["last_date"]),
    }


class LedgerReceivablesView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        book = _book(request.query_params.get("book"), allow_all=True)
        as_of = _as_of(request)
        data = ledger.report(book, as_of, _months(request))
        rows = data["rows"]
        q = request.query_params.get("q", "").strip()
        if q:
            rows = [r for r in rows if q in r["name"] or q == (r["code"] or "")]
        if request.query_params.get("open") == "1":
            rows = [r for r in rows if r["balance"] != 0 or not r["has_ledger"]]
        keys = [c["key"] for c in data["columns"]]
        totals = {
            "buckets": {k: _s(sum((r["buckets"][k] for r in rows), Decimal(0))) for k in keys},
            "prepayment": _s(sum((r["prepayment"] for r in rows), Decimal(0))),
            "balance": _s(sum((r["balance"] for r in rows), Decimal(0))),
            "manual_balance": _s(sum((r["manual_balance"] or 0 for r in rows), Decimal(0))),
            "by_book": {b: _s(sum((r["by_book"].get(b, 0) for r in rows), Decimal(0))) for b in BOOKS},
        }
        return Response({
            "as_of": as_of.isoformat(), "book": book, "columns": data["columns"], "rows": [_row_json(r) for r in rows],
            "totals": totals,
            "counts": {
                "accounts": len(rows),
                "with_ledger": sum(1 for r in rows if r["has_ledger"]),
                "unreconciled": sum(1 for r in rows if r["has_ledger"] and not r["reconciled"]),
            },
            "books": [{"key": k, "label": v} for k, v in LedgerBook.choices],
        })


class LedgerReceivablesExportView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        book = _book(request.query_params.get("book"), allow_all=True)
        as_of = _as_of(request)
        content = ledger.collections_workbook(book, as_of, _months(request))
        resp = HttpResponse(content, content_type=XLSX)
        resp["Content-Disposition"] = f'attachment; filename="vosouli-{book}-{ledger.jdate(as_of).replace("/", "")}.xlsx"'
        return resp


def _parsed_json(p: ledger.Parsed) -> dict:
    from collections import Counter

    kinds = Counter(r.kind for r in p.rows)
    last = next((r.balance for r in reversed(p.rows) if r.balance is not None), None)
    return {
        "rows": len(p.rows), "sheet": p.sheet,
        "first_date": _iso(p.first_date), "last_date": _iso(p.last_date),
        "opening": _s(p.opening),
        "debit": _s(sum((r.debit for r in p.rows), Decimal(0))),
        "credit": _s(sum((r.credit for r in p.rows), Decimal(0))),
        "file_balance": _s(last),
        "invoices": kinds.get("invoice", 0), "receipts": kinds.get("receipt", 0),
        "returns": kinds.get("return", 0), "other": kinds.get("other", 0),
    }


def _read(request) -> tuple[ledger.Parsed, str]:
    upload = request.FILES.get("file")
    if not upload:
        raise ValidationError({"file": "فایل «دفتر حساب» آرپا را انتخاب کنید."})
    try:
        return ledger.read_file(upload), upload.name
    except ledger.LedgerFileError as e:
        raise ValidationError({"file": str(e)})


class LedgerPreviewView(APIView):
    """What the file holds and who it is probably for; writes nothing."""

    permission_classes = [Sales2Access]

    def post(self, request):
        parsed, name = _read(request)
        book = _book(request.data.get("book"))
        out = {"file": name, "parsed": _parsed_json(parsed), "suggestions": ledger.suggest_customers(name)}
        cid = request.data.get("customer")
        if cid:
            existing = LedgerAccount.objects.filter(book=book, customer_id=cid).first()
            out["replaces"] = {
                "rows": existing.entries.count(), "imported_at": existing.imported_at,
                "last_date": _iso(existing.last_date), "source_file": existing.source_file,
            } if existing and existing.imported_at else None
        return Response(out)


class LedgerImportView(APIView):
    """Replace one customer's ledger in one book with the file's."""

    permission_classes = [Sales2Access]

    def post(self, request):
        parsed, name = _read(request)
        book = _book(request.data.get("book"))
        cid = request.data.get("customer")
        if not cid:
            raise ValidationError({"customer": "مشتری این دفتر را انتخاب کنید."})
        customer = get_object_or_404(Customer, pk=cid)
        acc = ledger.save(parsed, customer, book, request.user, name,
                          party_code=(request.data.get("party_code") or "").strip())
        a = ledger.analyse(acc)
        audit_log(request.user, acc, AuditLog.Action.IMPORT,
                  {"ledger_import": {"before": None, "after": f"{name}: {len(parsed.rows)} ردیف"}})
        return Response({
            "account": acc.pk, "customer": customer.pk, "name": customer.name_fa, "book": book,
            "parsed": _parsed_json(parsed), "balance": _s(a.balance), "reconciled": a.reconciled,
            "issues": [{"level": i.level, "message": i.message} for i in a.issues],
        })


class LedgerCollectionsImportView(APIView):
    """Bring «توضیحات»، «بازاریاب» and the hand-typed balances from «گزارش وصولی»."""

    permission_classes = [Sales2Access]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "فایل «گزارش وصولی» را انتخاب کنید."})
        book = _book(request.data.get("book"))
        try:
            res = ledger.import_collections(upload, book)
        except ledger.LedgerFileError as e:
            raise ValidationError({"file": str(e)})
        return Response({
            "sheet": res.sheet, "as_of": _iso(res.as_of), "matched": res.matched, "created": res.created,
            "unmatched": [{"code": c, "name": n, "balance": b} for c, n, b in res.unmatched],
        })


def _analysis_json(a: ledger.Analysis, as_of: date) -> dict:
    acc = a.account
    info = ledger.sales_invoices([acc.customer_id]) if acc.book == LedgerBook.MAIN else {}
    names = {i.key: (i.number or ("مانده قبل از دوره" if i.kind == "opening" else f"ردیف {i.row_no}"))
             for i in a.items}
    items = []
    for it in a.items:
        inv = info.get((acc.customer_id, it.number)) if it.kind == "invoice" else None
        due = inv["due_date"] if inv else None
        open_ = it.remaining > 0
        items.append({
            "key": it.key, "kind": it.kind, "number": it.number, "label": names[it.key],
            "date": _iso(it.date), "doc_no": it.doc_no, "amount": _s(it.amount), "paid": _s(it.paid),
            "returned": _s(it.returned), "remaining": _s(it.remaining), "settled_on": _iso(it.settled_on),
            "days_open": (as_of - it.date).days if open_ else None,
            "days_to_settle": (it.settled_on - it.date).days if it.settled_on else None,
            "due_date": _iso(due), "overdue_days": (as_of - due).days if open_ and due and as_of > due else None,
            "arpa_total": _s(inv["total"]) if inv else None, "salesperson": inv["owner"] if inv else "",
            "description": it.description,
            "payments": [{"date": _iso(p.date), "doc_no": p.doc_no, "amount": _s(p.amount),
                          "method": p.method, "how": p.how} for p in it.payments],
        })
    return {
        "account": {
            "id": acc.pk, "book": acc.book, "book_label": acc.get_book_display(), "customer": acc.customer_id,
            "name": acc.customer.name_fa, "party_code": acc.party_code, "note": acc.note, "marketer": acc.marketer,
            "source_file": acc.source_file, "imported_at": acc.imported_at,
            "first_date": _iso(acc.first_date), "last_date": _iso(acc.last_date), "opening": _s(acc.opening_rial),
            "manual_balance": _s(acc.manual_balance_rial), "manual_as_of": _iso(acc.manual_as_of),
        },
        "as_of": as_of.isoformat(),
        "balance": _s(a.balance), "file_balance": _s(a.file_balance), "prepayment": _s(a.prepayment),
        "reconciled": a.reconciled, "oldest_open": _iso(a.oldest_open),
        "issues": [{"level": i.level, "message": i.message, "row": i.row_no} for i in a.issues],
        "items": items,
        "credits": [{
            "date": _iso(c.date), "doc_no": c.doc_no, "fixed_no": c.fixed_no, "kind": c.kind, "method": c.method,
            "amount": _s(c.amount), "invoice_no": c.invoice_no, "cheque_count": c.cheque_count,
            "left": _s(c.left), "description": c.description,
            "allocations": [{"label": names.get(k, k), "amount": _s(v), "how": how} for k, v, how in c.allocations],
        } for c in a.credits],
        "rows": [{
            "row": e.row_no, "doc_no": e.doc_no, "fixed_no": e.fixed_no, "date": _iso(e.date),
            "debit": _s(e.debit_rial), "credit": _s(e.credit_rial), "balance": _s(bal),
            "file_balance": _s(e.file_balance_rial), "kind": e.kind, "invoice_no": e.invoice_no,
            "ticked": e.ticked, "description": e.description,
        } for e, bal in a.running],
    }


class LedgerAccountView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request, pk):
        acc = get_object_or_404(LedgerAccount.objects.select_related("customer"), pk=pk)
        as_of = _as_of(request)
        return Response(_analysis_json(ledger.analyse(acc, as_of), as_of))

    def patch(self, request, pk):
        acc = get_object_or_404(LedgerAccount, pk=pk)
        before = {f: getattr(acc, f) for f in ("note", "marketer", "party_code")}
        for f, n in (("note", 400), ("marketer", 100), ("party_code", 32)):
            if f in request.data:
                setattr(acc, f, str(request.data.get(f) or "").strip()[:n])
        acc.save()
        audit_log(request.user, acc, AuditLog.Action.UPDATE,
                  {f: {"before": before[f], "after": getattr(acc, f)} for f in before if before[f] != getattr(acc, f)})
        return Response({"id": acc.pk, "note": acc.note, "marketer": acc.marketer, "party_code": acc.party_code})

    def delete(self, request, pk):
        acc = get_object_or_404(LedgerAccount, pk=pk)
        audit_log(request.user, acc, AuditLog.Action.DELETE, {"entries": {"before": acc.entries.count(), "after": 0}})
        acc.delete()
        return Response(status=204)


class LedgerCustomerExportView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        as_of = _as_of(request)
        resp = HttpResponse(ledger.customer_workbook(customer, as_of), content_type=XLSX)
        resp["Content-Disposition"] = f'attachment; filename="statement-{pk}-{ledger.jdate(as_of).replace("/", "")}.xlsx"'
        return resp
