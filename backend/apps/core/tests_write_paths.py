"""
Every write path of فروش، مالی and بازرگانی, fed the input people really send.

A text where a number belongs, an id that no longer exists, a cell from a
stale page — each must come back as a 400 with a sentence, never as «خطای
سرور», and must never leave a row pointing at nothing. Foreign keys are
checked after every request because SQLite only enforces them at commit, so
a dangling row would otherwise pass here and fail on the server.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.commercial.models import (
    Bank, Currency, ForeignOrder, Material, MaterialCategory, MaterialUnit,
    PurchaseRequest, Supplier,
)
from apps.core.models import DimPeriod, PeriodKind
from apps.finance.budget_models import Budget
from apps.sales.models import DimEmployee, DimProvince


class WritePathTests(APITestCase):
    def setUp(self):
        U = get_user_model()
        self.ceo = U.objects.create_user("probe_ceo", password="x", role="executive")
        self.finance = U.objects.create_user(
            "probe_fin", password="x", role="manager", department="finance")
        self.commercial = U.objects.create_user(
            "probe_com", password="x", role="manager", department="commercial")
        self.sales = U.objects.create_user(
            "probe_sales", password="x", role="manager", department="sales_team")

        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=7, kind=PeriodKind.MONTH,
            start_date=date(2026, 9, 23), end_date=date(2026, 10, 22),
        )
        self.emp = DimEmployee.objects.create(code="p1", full_name_fa="آزمون")
        self.prov = DimProvince.objects.create(code="prb", name_fa="استان")
        self.material = Material.objects.create(
            code="probe-mat", name_fa="کالا",
            category=MaterialCategory.objects.first(), unit=MaterialUnit.ROLL)
        self.supplier = Supplier.objects.create(code="probe-sup", name_fa="تامین")
        self.bank = Bank.objects.create(code="pb", name_fa="بانک")
        self.request_row = PurchaseRequest.objects.create(
            material=self.material, quantity=Decimal(5),
            requester_unit="خط", requested_on=date(2026, 9, 1))
        self.budget = Budget.objects.create(
            title="بودجه آزمون", jalali_year=1405,
            start_period=self.month, end_period=self.month)

    def probe(self, user, cases):
        from django.db import IntegrityError, connection, transaction

        class Rollback(Exception):
            pass

        crashes = []
        for label, method, url, payload in cases:
            self.client.force_authenticate(user)
            try:
                with transaction.atomic():
                    fn = getattr(self.client, method)
                    try:
                        response = fn(url, payload, format="json")
                        code = response.status_code
                        if code >= 500:
                            crashes.append((label, code, str(response.data)[:160]))
                    except Exception as exc:  # noqa: BLE001
                        crashes.append((label, "EXCEPTION", f"{type(exc).__name__}: {exc}"[:200]))
                    try:
                        connection.check_constraints()
                    except IntegrityError as exc:
                        crashes.append((label, "DANGLING-FK", str(exc)[:200]))
                    raise Rollback()
            except Rollback:
                pass
        return crashes

    def real_objects(self):
        from apps.commercial.models import Quote
        from apps.finance.budget_models import BudgetLine, BudgetPeriod
        from apps.finance.models import CashCategory, CashMovement, Direction
        cat = CashCategory.objects.get(code="supplier-other")
        self.line = BudgetLine.objects.create(budget=self.budget, category=cat, direction="out")
        self.bp = BudgetPeriod.objects.create(budget=self.budget, period=self.month)
        self.mov = CashMovement.objects.create(
            period=self.month, direction=Direction.OUT, category=cat, amount_rial=Decimal(5))
        self.cat = cat
        other = PurchaseRequest.objects.create(
            material=self.material, quantity=Decimal(1), requester_unit="خط",
            requested_on=date(2026, 9, 2))
        self.q1 = Quote.objects.create(request=self.request_row, supplier=self.supplier,
                                       unit_price_rial=Decimal(100))
        self.q_other = Quote.objects.create(request=other, supplier=self.supplier,
                                            unit_price_rial=Decimal(90))

    def test_no_write_path_crashes_or_stores_a_dangling_row(self):
        self.real_objects()
        m = self.month.id
        cases = [
            # ---- sales -------------------------------------------------
            ("sales input: no body", "post", "/api/sales/input/", {}),
            ("sales input: bogus period", "post", "/api/sales/input/", {"period": 999999}),
            ("sales input: bogus employee", "post", "/api/sales/input/",
             {"period": m, "columns": [{"name": "x", "employee_id": 999999}]}),
            ("sales input: text amount", "post", "/api/sales/input/",
             {"period": m, "columns": [{"name": "آزمون", "employee_id": self.emp.id,
                                        "revenue_rial": "abc"}]}),
            ("sales input: negative amount", "post", "/api/sales/input/",
             {"period": m, "columns": [{"name": "آزمون", "employee_id": self.emp.id,
                                        "revenue_rial": "-5000"}]}),
            ("sales input: bogus province", "post", "/api/sales/input/",
             {"period": m, "provinces": [{"province_id": 999999, "sales_rial": "10"}]}),
            ("sales input: bogus channel", "post", "/api/sales/input/",
             {"period": m, "channel": "not-a-channel",
              "columns": [{"name": "آزمون", "employee_id": self.emp.id}]}),
            ("sales targets: bogus employee", "post", "/api/sales/targets/",
             {"period": m, "people": [{"employee_id": 999999, "target_rial": "10"}]}),
            ("sales targets: bogus province", "post", "/api/sales/targets/",
             {"period": m, "provinces": [{"province_id": 999999, "target_rial": "10"}]}),
            ("sales targets: text target", "post", "/api/sales/targets/",
             {"period": m, "people": [{"employee_id": self.emp.id, "target_rial": "abc"}]}),
            ("sales targets: bogus channel", "post", "/api/sales/targets/",
             {"period": m, "channel": "zzz",
              "people": [{"employee_id": self.emp.id, "target_rial": "1"}]}),
            ("sales approvals decide: empty", "post", "/api/sales/approvals/decide/", {}),
            ("sales approvals decide: bogus", "post", "/api/sales/approvals/decide/",
             {"period": 999999, "channel": "zzz", "decision": "approve"}),
            ("kpi recompute: bogus period", "post", "/api/sales/kpi-results/recompute/",
             {"period": 999999}),
            # ---- finance -----------------------------------------------
            ("finance entry: no body", "post", "/api/finance/entry/", {}),
            ("finance entry: bogus category", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m, "in": {"999999": [{"amount_rial": "5"}]}}]}),
            ("finance entry: bogus account", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m, "in": {}, "out": {}}]}),
            ("finance entry: text amount", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m, "in": {}, "out": {}}], "submit": "yes"}),
            ("budget grid: bogus ids", "post", "/api/finance/budget-grid/",
             {"cells": [{"budget_period_id": 999999, "line_id": 999999, "amount_rial": "5"}]}),
            ("budget grid: text amount", "post", "/api/finance/budget-grid/",
             {"cells": [{"budget_period_id": 1, "line_id": 1, "amount_rial": "abc"}]}),
            ("budget actuals: bogus line", "post", "/api/finance/budget-actuals/",
             {"budget": self.budget.id, "period": m,
              "cells": [{"line_id": 999999, "amount_rial": "5"}]}),
            ("budget actuals: text amount", "post", "/api/finance/budget-actuals/",
             {"budget": self.budget.id, "period": m,
              "cells": [{"line_id": 1, "amount_rial": "abc"}]}),
            ("budget notes: empty", "post", "/api/finance/budget-notes/", {}),
            ("budget approve: bogus", "post",
             f"/api/finance/budgets/{self.budget.id}/approve/", {"period": 999999}),
            ("budget line: bogus category", "post", "/api/finance/budget-lines/",
             {"budget": self.budget.id, "category": 999999, "direction": "out"}),
            ("cash category: duplicate code", "post", "/api/finance/categories/",
             {"code": "sales-other", "name_fa": "تکراری", "direction": "in"}),
            # ---- commercial --------------------------------------------
            ("request create: empty", "post", "/api/commercial/requests/", {}),
            ("request create: bogus material", "post", "/api/commercial/requests/",
             {"material": 999999, "quantity": "5", "requested_on": "2026-09-01"}),
            ("request create: negative qty", "post", "/api/commercial/requests/",
             {"material": self.material.id, "quantity": "-5",
              "requester_unit": "خط", "requested_on": "2026-09-01"}),
            ("request create: bad date", "post", "/api/commercial/requests/",
             {"material": self.material.id, "quantity": "5",
              "requester_unit": "خط", "requested_on": "not-a-date"}),
            ("award: empty", "post",
             f"/api/commercial/requests/{self.request_row.id}/award/", {}),
            ("award: bogus quote", "post",
             f"/api/commercial/requests/{self.request_row.id}/award/",
             {"winner_quote_id": 999999, "reasons": []}),
            ("quick quote: empty", "post", "/api/commercial/quotes/quick/", {}),
            ("quick quote: bogus ids", "post", "/api/commercial/quotes/quick/",
             {"material": 999999, "supplier": 999999, "unit_price_rial": "abc"}),
            ("order create: empty", "post", "/api/commercial/orders/", {}),
            ("order create: bogus supplier", "post", "/api/commercial/orders/",
             {"material": self.material.id, "supplier": 999999, "quantity": "1",
              "unit_price_rial": "10", "ordered_on": "2026-09-01"}),
            ("foreign order: empty", "post", "/api/commercial/foreign/orders/", {}),
            ("foreign order: bogus bank", "post", "/api/commercial/foreign/orders/",
             {"pi_no": "X", "supplier": self.supplier.id, "bank": 999999,
              "currency": Currency.USD, "amount": "10", "registered_on": "2026-09-01"}),
            ("shipment: bogus order", "post", "/api/commercial/foreign/shipments/",
             {"order": 999999, "container_no": "C1"}),
            ("cost: bogus order", "post", "/api/commercial/foreign/costs/",
             {"order": 999999, "amount_rial": "10", "kind": "duty"}),
            # ---- with real rows ----------------------------------------
            ("budget grid: text amount on real cell", "post", "/api/finance/budget-grid/",
             {"cells": [{"budget_period_id": self.bp.id, "line_id": self.line.id,
                         "amount_rial": "abc"}]}),
            ("budget grid: negative amount", "post", "/api/finance/budget-grid/",
             {"cells": [{"budget_period_id": self.bp.id, "line_id": self.line.id,
                         "amount_rial": "-9"}]}),
            ("finance entry: text amount on existing row", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m,
              "out": {str(self.cat.id): [{"amount_rial": "abc"}]}}]}),
            ("finance entry: bogus account id", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m,
              "out": {str(self.cat.id): [{"amount_rial": "7", "account": 999999}]}}]}),
            ("finance entry: bogus credit line", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": m,
              "out": {str(self.cat.id): [{"amount_rial": "7", "credit_line": 999999}]}}]}),
            ("finance entry: bogus day id", "post", "/api/finance/entry/",
             {"period": m, "days": [{"period_id": 999999,
              "out": {str(self.cat.id): [{"amount_rial": "7"}]}}]}),
            ("award: quote of another request", "post",
             f"/api/commercial/requests/{self.request_row.id}/award/",
             {"quote": self.q_other.id}),
            ("award: text rejection id", "post",
             f"/api/commercial/requests/{self.request_row.id}/award/",
             {"quote": self.q1.id, "rejections": [{"quote": "abc"}]}),
            ("quote patch: text price", "patch", f"/api/commercial/quotes/{self.q1.id}/",
             {"unit_price_rial": "abc"}),
            ("quote patch: negative price", "patch", f"/api/commercial/quotes/{self.q1.id}/",
             {"unit_price_rial": "-100"}),
        ]
        crashes = []
        for user in (self.ceo, self.finance, self.commercial, self.sales):
            for label, code, detail in self.probe(user, cases):
                crashes.append(f"[{user.username}] {label} -> {code} | {detail}")
        self.assertEqual(crashes, [], "\n" + "\n".join(crashes))
