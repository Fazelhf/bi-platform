from django.db.models import F, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import DimPeriod, FactKPI, KPIScope
from apps.production.models import (
    DimCostCategory,
    DimMachine,
    DimProduct,
    FactMaterialBalance,
    FactPrintColor,
    FactProduction,
    FactProductionCost,
    FactProductionRevenue,
    ProductionBenchmark,
    Shift,
)
from apps.production.serializers import (
    BenchmarkSerializer,
    CostCategorySerializer,
    MachineSerializer,
    MaterialBalanceSerializer,
    PrintColorSerializer,
    ProductSerializer,
    ProductionCostSerializer,
    ProductionRevenueSerializer,
    ProductionSerializer,
)
from apps.core.audit import diff as audit_diff, log as audit_log, snapshot
from apps.core.models import AuditLog
from apps.core.approval import submission_status
from apps.core.notify import notify_decision, notify_submitted
from apps.core.permissions import ApprovalPermission, DepartmentEntryPermission
from apps.production.services.kpi import compute_period_kpis
from apps.sales.models import ApprovalStatus
from apps.sales.permissions import CanApprove, CanEnterData
from apps.sales.serializers import KPIResultSerializer, PeriodSerializer


# -------------------- Dimensions --------------------
class MachineViewSet(viewsets.ModelViewSet):
    queryset = DimMachine.objects.all()
    serializer_class = MachineSerializer
    filterset_fields = ["kind", "is_active"]


class ProductViewSet(viewsets.ModelViewSet):
    queryset = DimProduct.objects.all()
    serializer_class = ProductSerializer


class CostCategoryViewSet(viewsets.ModelViewSet):
    queryset = DimCostCategory.objects.all()
    serializer_class = CostCategorySerializer


class BenchmarkViewSet(viewsets.ModelViewSet):
    queryset = ProductionBenchmark.objects.select_related("period").all()
    serializer_class = BenchmarkSerializer
    permission_classes = [CanApprove]
    filterset_fields = ["period"]


# -------------------- Facts --------------------
class ProductionViewSet(viewsets.ModelViewSet):
    """Excel-like production entry grid, with the same approval workflow as sales."""

    queryset = FactProduction.objects.select_related("machine", "period").all()
    serializer_class = ProductionSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "machine", "status", "shift"]

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save(status=ApprovalStatus.DRAFT)
        audit_log(self.request.user, instance, AuditLog.Action.UPDATE,
                  audit_diff(before, snapshot(instance)))

    def _detail(self, fact) -> str:
        return f"تولید {fact.machine.name_fa} ({fact.get_shift_display()}) · {fact.period.label}"

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        fact = self.get_object()
        fact.status = submission_status(request.user, "production", True)
        fact.submitted_by = request.user
        fields = ["status", "submitted_by", "updated_at"]
        if fact.status == ApprovalStatus.APPROVED:
            fact.approved_by = request.user
            fields.append("approved_by")
        fact.save(update_fields=fields)
        audit_log(request.user, fact, AuditLog.Action.SUBMIT)
        if fact.status == ApprovalStatus.APPROVED:
            compute_period_kpis(fact.period)
        else:
            notify_submitted(request.user, fact, "production", self._detail(fact))
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission])
    def approve(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.APPROVED
        fact.approved_by = request.user
        fact.save(update_fields=["status", "approved_by", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.APPROVE)
        notify_decision(request.user, fact, "approved", self._detail(fact))
        compute_period_kpis(fact.period)
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission])
    def reject(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.REJECTED
        fact.save(update_fields=["status", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.REJECT)
        notify_decision(request.user, fact, "rejected", self._detail(fact))
        return Response(self.get_serializer(fact).data)

    @action(detail=True, methods=["post"], permission_classes=[ApprovalPermission],
            url_path="request-revision")
    def request_revision(self, request, pk=None):
        fact = self.get_object()
        fact.status = ApprovalStatus.NEEDS_REVISION
        fact.save(update_fields=["status", "updated_at"])
        audit_log(request.user, fact, AuditLog.Action.REVISION,
                  {"note": {"before": None, "after": request.data.get("note", "")}})
        notify_decision(request.user, fact, "revision", self._detail(fact))
        return Response(self.get_serializer(fact).data)


class ProductionCostViewSet(viewsets.ModelViewSet):
    queryset = FactProductionCost.objects.select_related("category", "period").all()
    serializer_class = ProductionCostSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "category"]


class ProductionRevenueViewSet(viewsets.ModelViewSet):
    queryset = FactProductionRevenue.objects.select_related("product", "period").all()
    serializer_class = ProductionRevenueSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "product"]


class PrintColorViewSet(viewsets.ModelViewSet):
    queryset = FactPrintColor.objects.select_related("period").all()
    serializer_class = PrintColorSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period"]


class MaterialBalanceViewSet(viewsets.ModelViewSet):
    queryset = FactMaterialBalance.objects.select_related("period").all()
    serializer_class = MaterialBalanceSerializer
    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"
    filterset_fields = ["period", "stream"]


# -------------------- Production dashboard --------------------
class ProductionDashboardView(APIView):
    """Everything the production dashboard needs, in one call."""

    @extend_schema(
        parameters=[OpenApiParameter("period", int, required=True)],
        responses=dict,
    )
    def get(self, request):
        period = DimPeriod.objects.get(pk=request.query_params.get("period"))

        company_kpis = FactKPI.objects.filter(
            period=period, scope=KPIScope.COMPANY, kpi__domain="production"
        ).select_related("kpi")

        machine_kpis = FactKPI.objects.filter(
            period=period, scope=KPIScope.MACHINE
        ).select_related("kpi")

        from django.db.models import Avg

        from apps.core.periods import month_of, unit_ids

        # At تولید's own grain: a month recorded week by week is its weeks.
        units = unit_ids(period, "production")
        machines = (
            FactProduction.objects.filter(period_id__in=units)
            .values("machine__name_fa", "machine__kind", "machine__sort_order")
            .annotate(
                active_shifts=Sum("active_shifts"),
                output_units=Sum("output_units"),
                actual_journal=Sum("actual_journal"),
                actual_pos=Sum("actual_pos"),
                actual_receipt=Sum("actual_receipt"),
                waste_pct=Avg("waste_pct"),
                downtime_breakdown_shifts=Sum("downtime_breakdown_shifts"),
                downtime_sizechange_shifts=Sum("downtime_sizechange_shifts"),
                downtime_nowork_shifts=Sum("downtime_nowork_shifts"),
            )
            .order_by("machine__sort_order")
        )

        cutting_rows = FactProduction.objects.filter(
            period_id__in=units, machine__kind=DimMachine.Kind.CUTTING
        )
        shifts_by_machine = list(
            cutting_rows.values("machine__name_fa", "machine__sort_order", "shift")
            .annotate(
                output_units=Sum("output_units"),
                actual_journal=Sum("actual_journal"),
                actual_pos=Sum("actual_pos"),
                actual_receipt=Sum("actual_receipt"),
                active_shifts=Sum("active_shifts"),
            )
            .order_by("machine__sort_order", "shift")
        )

        costs = list(
            FactProductionCost.objects.filter(period_id__in=units)
            .values("category__name_fa")
            .annotate(amount=Sum("amount_rial"))
            .order_by("-amount")
        )

        # «سایر» says what it was for — one note per shift that wrote one.
        other_notes = [
            {"shift": c.shift, "shift_label": c.get_shift_display(),
             "description": c.description.strip(), "amount_rial": c.amount_rial}
            for c in FactProductionCost.objects.filter(
                period_id__in=units, category__code="cost-other",
            ).exclude(description="").order_by("shift")
            if c.description.strip()
        ]

        # What the form's notes said: each line's remarks and the press's
        # design, per shift and per week/day the month was recorded at.
        line_notes = [
            {"machine": f.machine.name_fa, "kind": f.machine.kind,
             "shift": f.shift, "shift_label": f.get_shift_display(),
             "period_label": f.period.label,
             "description": f.description.strip(), "print_design": f.print_design.strip()}
            for f in FactProduction.objects.filter(period_id__in=units)
            .exclude(description="", print_design="")
            .select_related("machine", "period")
            .order_by("period__start_date", "machine__sort_order", "shift")
            if f.description.strip() or f.print_design.strip()
        ]

        # Roll counts: one line per product, both shifts (and every week or
        # day of the month) added together.
        revenue_by_product: dict[str, dict] = {}
        revenue_by_shift = {Shift.DAY: 0, Shift.NIGHT: 0}
        for r in FactProductionRevenue.objects.filter(
            period_id__in=units
        ).select_related("product").order_by("product__sort_order"):
            row = revenue_by_product.setdefault(
                r.product.name_fa, {"product": r.product.name_fa, "quantity": 0, "amount": 0}
            )
            row["quantity"] += r.quantity
            row["amount"] += r.amount_rial
            revenue_by_shift[r.shift] += r.amount_rial
        revenue = list(revenue_by_product.values())

        print_colors = (
            FactPrintColor.objects.filter(period_id__in=units)
            .values("color_count").annotate(area_sqm=Sum("area_sqm"))
            .order_by("color_count")
        )

        # Day against night, section by section — the input form's four
        # tables, summed per shift.
        def per_shift(qs, **agg):
            return {r["shift"]: r for r in qs.values("shift").annotate(**agg)}

        cut = per_shift(
            cutting_rows,
            index_output=Sum("output_units"), journal=Sum("actual_journal"),
            pos=Sum("actual_pos"), receipt=Sum("actual_receipt"),
            active_shifts=Sum("active_shifts"),
            downtime=Sum(F("downtime_breakdown_shifts") + F("downtime_sizechange_shifts")
                         + F("downtime_nowork_shifts")),
        )
        printed = per_shift(FactPrintColor.objects.filter(period_id__in=units), area=Sum("area_sqm"))
        spent = per_shift(FactProductionCost.objects.filter(period_id__in=units), amount=Sum("amount_rial"))

        bench, _ = ProductionBenchmark.objects.get_or_create(period=month_of(period))
        shift_summary = []
        for shift, label in Shift.choices:
            c = cut.get(shift, {})
            journal, pos, receipt = (c.get(k) or 0 for k in ("journal", "pos", "receipt"))
            shift_summary.append({
                "shift": shift,
                "label": label,
                "index_output": c.get("index_output") or 0,
                "journal": journal,
                "pos": pos,
                "receipt": receipt,
                "actual_total": journal + pos + receipt,
                "active_shifts": c.get("active_shifts") or 0,
                "downtime": c.get("downtime") or 0,
                "print_area": printed.get(shift, {}).get("area") or 0,
                "cost": spent.get(shift, {}).get("amount") or 0,
                "revenue": revenue_by_shift[shift],
                "headcount": bench.headcount_night if shift == Shift.NIGHT else bench.headcount_day,
            })

        total_cost = sum((c["amount"] for c in costs), 0)
        total_revenue = sum((r["amount"] for r in revenue), 0)

        return Response(
            {
                "period": PeriodSerializer(period).data,
                "kpis": KPIResultSerializer(company_kpis, many=True).data,
                "machine_kpis": KPIResultSerializer(machine_kpis, many=True).data,
                "machines": list(machines),
                "shift_summary": shift_summary,
                "shifts_by_machine": shifts_by_machine,
                "costs": costs,
                "other_cost_notes": other_notes,
                "line_notes": line_notes,
                "revenue": revenue,
                "print_colors": list(print_colors),
                "days_in_month": bench.days_in_month,
                "financials": {
                    "revenue": total_revenue,      # درآمد
                    "cost": total_cost,            # هزینه
                    "net": total_revenue - total_cost,  # کارکرد / سود
                },
            }
        )


class RecomputeProductionView(APIView):
    permission_classes = [CanApprove]

    @extend_schema(parameters=[OpenApiParameter("period", int)], responses=dict)
    def post(self, request):
        period_id = request.data.get("period") or request.query_params.get("period")
        period = DimPeriod.objects.get(pk=period_id)
        n = compute_period_kpis(period)
        return Response({"period": period.label, "rows_written": n})


# --------------------------------------------------------------------------
# Combined production INPUT — the manager fills all four Excel tables here
# --------------------------------------------------------------------------
CUT_FIELDS = [
    "active_shifts", "output_units",
    "actual_journal", "actual_pos", "actual_receipt",
    "waste_pct", "repair_count",
    "downtime_breakdown_shifts", "downtime_sizechange_shifts", "downtime_nowork_shifts",
]
# Free text on a line's row: notes on any line, and the print unit's design.
TEXT_FIELDS = ["description", "print_design"]


class ProductionInputView(APIView):
    """
    One endpoint that mirrors the production workbook's four input tables:
      1) cutting lines (برش ۱–۵) · 2) resources & costs (منابع) ·
      3) print by colour (چاپ) · 4) roll counts (تعداد رول).
    GET returns everything for a period; POST upserts everything at once.
    """

    permission_classes = [DepartmentEntryPermission]
    entry_department = "production"

    def _bench(self, period):
        # The benchmark (headcount, capacity) is the month's, whatever grain
        # the lines are recorded at.
        from apps.core.periods import month_of

        b, _ = ProductionBenchmark.objects.get_or_create(period=month_of(period))
        return b

    @extend_schema(parameters=[OpenApiParameter("period", int, required=True)], responses=dict)
    def get(self, request):
        """Everything for the period, once per shift: {shifts: {day: {...}, night: {...}}}."""
        from apps.core.periods import grain_of, is_unit

        period = DimPeriod.objects.get(pk=request.query_params.get("period"))
        bench = self._bench(period)

        machines = list(DimMachine.objects.all())
        categories = list(DimCostCategory.objects.all())
        products = list(DimProduct.objects.all())
        facts = {(f.machine_id, f.shift): f for f in FactProduction.objects.filter(period=period)}
        colors = {(c.color_count, c.shift): c for c in FactPrintColor.objects.filter(period=period)}
        costs = {(c.category_id, c.shift): c for c in FactProductionCost.objects.filter(period=period)}
        rolls = {(r.product_id, r.shift): r for r in FactProductionRevenue.objects.filter(period=period)}

        def machine_row(m, shift):
            f = facts.get((m.id, shift))
            row = {"machine": m.id, "machine_name": m.name_fa, "kind": m.kind,
                   "status": f.status if f else "draft"}
            for fld in CUT_FIELDS:
                row[fld] = str(getattr(f, fld)) if f else "0"
            for fld in TEXT_FIELDS:
                row[fld] = getattr(f, fld) if f else ""
            return row

        def block(shift):
            print_machine = next((m for m in machines if m.kind == DimMachine.Kind.PRINT), None)
            return {
                "headcount": bench.headcount_night if shift == Shift.NIGHT else bench.headcount_day,
                "cutting": [machine_row(m, shift) for m in machines
                            if m.kind == DimMachine.Kind.CUTTING],
                "print": machine_row(print_machine, shift) if print_machine else None,
                "print_colors": [
                    {"color_count": n,
                     "area_sqm": str(colors[(n, shift)].area_sqm) if (n, shift) in colors else "0"}
                    for n in (1, 2, 3, 4)
                ],
                "costs": [
                    {"category": c.id, "category_code": c.code, "category_name": c.name_fa,
                     "amount_rial": str(costs[(c.id, shift)].amount_rial) if (c.id, shift) in costs else "0",
                     "description": costs[(c.id, shift)].description if (c.id, shift) in costs else ""}
                    for c in categories
                ],
                "rolls": [
                    {"product": p.id, "product_name": p.name_fa,
                     "piece_rate_rial": str(p.piece_rate_rial),
                     "quantity": str(rolls[(p.id, shift)].quantity) if (p.id, shift) in rolls else "0"}
                    for p in products
                ],
            }

        return Response({
            "period": PeriodSerializer(period).data,
            # تولید records at its own grain (set by the CEO); the page picks a
            # week or a day when it is finer than the month.
            "grain": grain_of(period, "production"),
            "is_unit": is_unit(period, "production"),
            "benchmark": BenchmarkSerializer(bench).data,
            "shifts": {Shift.DAY: block(Shift.DAY), Shift.NIGHT: block(Shift.NIGHT)},
        })

    def post(self, request):
        from apps.core.periods import grain_of, is_unit

        period = DimPeriod.objects.get(pk=request.data.get("period"))
        if not is_unit(period, "production"):
            unit = {"month": "ماه", "week": "هفته", "day": "روز"}[grain_of(period, "production")]
            return Response(
                {"detail": f"اطلاعات تولید برای هر {unit} جداگانه وارد می‌شود؛ یک {unit} را انتخاب کنید."},
                status=400,
            )
        data = request.data
        user = request.user
        submit = bool(data.get("submit"))
        # An operator's submission waits for the production manager; the
        # manager's own is final as sent (apps.core.approval).
        status = submission_status(user, "production", submit)
        approved = status == ApprovalStatus.APPROVED

        # {day: {...}, night: {...}}. A flat body (the pre-shift format, and
        # what older clients still send) is the day shift's.
        shifts = data.get("shifts") or {Shift.DAY: data}
        bench = self._bench(period)

        for shift, block in shifts.items():
            if shift not in Shift.values:
                continue

            # 1) Headcount — total stays the sum the KPIs read.
            hc = block.get("headcount", block.get("total_headcount"))
            if hc is not None:
                setattr(bench, f"headcount_{shift}", int(float(hc or 0)))

            # 2) Machines (cutting + print)
            rows = list(block.get("cutting", [])) + ([block["print"]] if block.get("print") else [])
            for row in rows:
                defaults = {f: (row.get(f) or 0) for f in CUT_FIELDS}
                # Sent only by clients that know the fields; older ones keep what is stored.
                defaults.update({f: (row[f] or "").strip() for f in TEXT_FIELDS if f in row})
                defaults["status"] = status
                if submit:
                    defaults["submitted_by"] = user
                if approved:
                    defaults["approved_by"] = user
                obj, _ = FactProduction.objects.update_or_create(
                    period=period, machine_id=row["machine"], shift=shift, defaults=defaults
                )
                audit_log(user, obj, AuditLog.Action.UPDATE)

            # 3) Print colours
            for c in block.get("print_colors", []):
                FactPrintColor.objects.update_or_create(
                    period=period, color_count=int(c["color_count"]), shift=shift,
                    defaults={"area_sqm": c.get("area_sqm") or 0},
                )

            # 4) Costs
            for c in block.get("costs", []):
                FactProductionCost.objects.update_or_create(
                    period=period, category_id=c["category"], shift=shift,
                    defaults={"amount_rial": c.get("amount_rial") or 0,
                              "description": c.get("description") or ""},
                )

            # 5) Roll counts (revenue)
            for r in block.get("rolls", []):
                product = DimProduct.objects.get(pk=r["product"])
                FactProductionRevenue.objects.update_or_create(
                    period=period, product=product, shift=shift,
                    defaults={"quantity": r.get("quantity") or 0,
                              "piece_rate_rial": product.piece_rate_rial},
                )

        if bench.headcount_day or bench.headcount_night:
            bench.total_headcount = bench.headcount_day + bench.headcount_night
        bench.save(update_fields=["headcount_day", "headcount_night", "total_headcount"])

        # Material balance from paper weights (optional inputs)
        if "input_weight" in data or "output_weight" in data:
            FactMaterialBalance.objects.update_or_create(
                period=period, stream=FactMaterialBalance.Stream.CUTTING,
                defaults={"input_weight": data.get("input_weight") or 0,
                          "output_weight": data.get("output_weight") or 0},
            )

        if approved:
            compute_period_kpis(period)
        elif submit:
            # Tell the production manager that figures are pending.
            first = FactProduction.objects.filter(period=period).first()
            if first:
                notify_submitted(user, first, "production", f"اطلاعات تولید · {period.label}")

        return Response({"ok": True, "submitted": submit, "status": status, "period": period.label})
