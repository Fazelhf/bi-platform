"""گرید مشتری و شاخص‌های فروش — کتاب فروش، فصل ۱۲، ۱۶ و ۱۷."""
from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.crm.models import Customer
from apps.sales2 import grading, kpis
from apps.sales2.models import CustomerAccount
from apps.sales2.permissions import Sales2Access
from apps.sales2.views_pricing import _month


class GradesView(APIView):
    """Every customer who bought in the last year: score, its parts, suggested and approved grade."""

    permission_classes = [Sales2Access]

    def get(self, request):
        scores = grading.compute()
        accounts = {a.customer_id: a for a in CustomerAccount.objects.filter(
            Q(customer_id__in=list(scores)) | ~Q(grade="")).select_related("grade_set_by")}
        ids = set(scores) | set(accounts)
        missing = ids - set(scores)
        if missing:
            scores.update(grading.compute(missing))
        customers = {c.id: c for c in Customer.objects.filter(pk__in=ids).select_related("owner")}
        q = (request.query_params.get("q") or "").strip()
        rows = []
        for cid, s in scores.items():
            c = customers.get(cid)
            if c is None or (q and q not in c.name_fa and q not in c.code):
                continue
            acc = accounts.get(cid)
            rows.append({
                "customer": cid, "name": c.name_fa, "code": c.code,
                "owner_name": c.owner.full_name_fa if c.owner else "",
                "score": s.total, "suggested": s.suggested,
                "parts": {k: round(v) for k, v in s.parts.items()}, "facts": s.facts,
                "grade": acc.grade if acc else "",
                "strategic_score": acc.strategic_score if acc else 50,
                "grade_score": acc.grade_score if acc else None,
                "grade_note": acc.grade_note if acc else "",
                "grade_set_at": acc.grade_set_at if acc else None,
                "grade_set_by": (acc.grade_set_by.get_full_name() or acc.grade_set_by.username)
                if acc and acc.grade_set_by else "",
            })
        rows.sort(key=lambda r: -r["score"])
        return Response({"weights": grading.weights(), "parts": grading.PARTS, "rows": rows})


class GradeSetView(APIView):
    """تأیید گرید — management sets the grade (and the strategic part of the score)."""

    permission_classes = [Sales2Access]

    def post(self, request, customer_id: int):
        customer = get_object_or_404(Customer, pk=customer_id)
        before = CustomerAccount.objects.filter(customer=customer).values_list("grade", flat=True).first() or ""
        strategic = request.data.get("strategic_score")
        acc = grading.set_grade(customer, request.user, request.data.get("grade", ""),
                                request.data.get("note", "") or "",
                                None if strategic in (None, "") else int(strategic))
        audit_log(request.user, acc, AuditLog.Action.UPDATE,
                  {"grade": {"before": before, "after": acc.grade}})
        s = grading.score_of(customer)
        return Response({"grade": acc.grade, "strategic_score": acc.strategic_score,
                         "score": s.total if s else None, "suggested": s.suggested if s else None})


class KpiView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        jy, jm = _month(request)
        return Response(kpis.report(jy, jm))
