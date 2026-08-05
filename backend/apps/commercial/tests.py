"""
بازرگانی tests.

Three things have to be right:

* **Who may look.** Supplier prices are what the company pays; a sales manager
  reading them is a leak, not a convenience.
* **The award.** Choosing a supplier writes every quote in the استعلام at
  once. Two winners, or a losing quote with no recorded reason, would corrupt
  the supplier statistics that read straight off those flags.
* **The arithmetic.** Totals are computed rather than stored, price change is
  a percentage that must refuse to be invented, and the forecast has to stay
  sane on the two inputs it will really meet — a rising series and no series
  at all.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.commercial.models import (
    Material,
    MaterialCategory,
    MaterialUnit,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    QuoteReason,
    Supplier,
)
from apps.commercial.services import consumption, forecast, price_history, supplier_stats


def _user(username, role, department=""):
    User = get_user_model()
    return User.objects.create_user(
        username=username, password="pw12345!", role=role, department=department
    )


class CommercialTestCase(APITestCase):
    def setUp(self):
        self.packaging = MaterialCategory.objects.get(code="packaging")
        self.shrink = Material.objects.create(
            code="shrink-tape", name_fa="نوار شیرینگ",
            category=self.packaging, unit=MaterialUnit.ROLL,
        )
        self.a = Supplier.objects.create(code="sup-a", name_fa="شرکت الف")
        self.b = Supplier.objects.create(code="sup-b", name_fa="شرکت ب")
        self.c = Supplier.objects.create(code="sup-c", name_fa="شرکت ج")

        self.manager = _user("sadaf", "manager", "commercial")
        self.ceo = _user("ceo", "executive", "")
        self.sales = _user("sales", "manager", "sales_team")

    # -- helpers ---------------------------------------------------------
    def _request(self, qty=20, on=date(2026, 7, 25)):
        return PurchaseRequest.objects.create(
            material=self.shrink, quantity=Decimal(qty),
            requester_unit="خط بسته‌بندی", requested_on=on,
        )

    def _order(self, on, qty, price, status=PurchaseOrder.Status.DELIVERED,
               supplier=None):
        return PurchaseOrder.objects.create(
            supplier=supplier or self.a, material=self.shrink,
            quantity=Decimal(qty), unit_price_rial=Decimal(price),
            ordered_on=on, delivered_on=on if status == "delivered" else None,
            status=status,
        )


class PermissionTests(CommercialTestCase):
    def test_commercial_manager_may_write(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post("/api/commercial/suppliers/", {
            "name_fa": "شرکت جدید",
        })
        self.assertEqual(response.status_code, 201)
        # The code is derived rather than demanded — a Persian name gives no
        # usable slug, so the API must not make the user invent one.
        self.assertTrue(response.data["code"])

    def test_ceo_reads_but_does_not_write(self):
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.get("/api/commercial/suppliers/").status_code, 200)
        self.assertEqual(
            self.client.post("/api/commercial/suppliers/", {"name_fa": "x"}).status_code,
            403,
        )

    def test_sales_manager_gets_nothing(self):
        self.client.force_authenticate(self.sales)
        for url in (
            "/api/commercial/suppliers/",
            "/api/commercial/materials/",
            "/api/commercial/dashboard/",
            "/api/commercial/reports/purchases/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_anonymous_gets_nothing(self):
        self.assertEqual(
            self.client.get("/api/commercial/materials/").status_code, 401
        )


class DocumentNumberTests(CommercialTestCase):
    def test_numbers_are_sequential_within_a_jalali_year(self):
        first = self._request()
        second = self._request()
        self.assertTrue(first.request_no.startswith("PR-1405-"))
        self.assertEqual(
            int(second.request_no.rsplit("-", 1)[1]),
            int(first.request_no.rsplit("-", 1)[1]) + 1,
        )

    def test_deleting_the_last_row_does_not_reissue_its_number(self):
        first = self._request()
        second = self._request()
        taken = second.request_no
        second.delete()
        third = self._request()
        # Derived from the highest number, not from a count: reusing a
        # document number would make two different requests share an identity
        # in anyone's records.
        self.assertNotEqual(third.request_no, taken)
        self.assertNotEqual(third.request_no, first.request_no)


class AwardTests(CommercialTestCase):
    def setUp(self):
        super().setUp()
        self.req = self._request()
        self.q_a = Quote.objects.create(
            request=self.req, supplier=self.a,
            unit_price_rial=Decimal(950_000), delivery_days=2, validity_days=5,
        )
        self.q_b = Quote.objects.create(
            request=self.req, supplier=self.b,
            unit_price_rial=Decimal(980_000), delivery_days=1, validity_days=3,
        )
        self.q_c = Quote.objects.create(
            request=self.req, supplier=self.c,
            unit_price_rial=Decimal(940_000), delivery_days=5, validity_days=7,
        )
        self.win_quality = QuoteReason.objects.get(code="better-quality")
        self.lose_price = QuoteReason.objects.get(code="high-price")
        self.lose_late = QuoteReason.objects.get(code="late-delivery")

    def test_award_records_a_reason_on_every_quote(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            f"/api/commercial/requests/{self.req.id}/award/",
            {
                "quote": self.q_a.id,
                "reason": self.win_quality.id,
                "decision_note": "کیفیت چسبندگی بهتر",
                "rejections": [
                    {"quote": self.q_b.id, "reason": self.lose_price.id},
                    {"quote": self.q_c.id, "reason": self.lose_late.id,
                     "decision_note": "۵ روز برای خط دیر است"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)

        self.q_a.refresh_from_db()
        self.q_b.refresh_from_db()
        self.q_c.refresh_from_db()

        self.assertTrue(self.q_a.is_selected)
        self.assertEqual(self.q_a.reason, self.win_quality)
        self.assertFalse(self.q_b.is_selected)
        self.assertEqual(self.q_b.reason, self.lose_price)
        # The cheapest quote losing is the case the price file exists for:
        # the reason must survive, not the price alone.
        self.assertEqual(self.q_c.reason, self.lose_late)
        self.assertEqual(self.q_c.decision_note, "۵ روز برای خط دیر است")

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, PurchaseRequest.Status.AWARDED)

    def test_awarding_again_leaves_exactly_one_winner(self):
        self.client.force_authenticate(self.manager)
        for quote in (self.q_a, self.q_c):
            self.client.post(
                f"/api/commercial/requests/{self.req.id}/award/",
                {"quote": quote.id}, format="json",
            )
        self.assertEqual(self.req.quotes.filter(is_selected=True).count(), 1)
        self.assertEqual(self.req.quotes.get(is_selected=True).id, self.q_c.id)

    def test_a_quote_from_another_request_is_refused(self):
        other = self._request()
        stray = Quote.objects.create(
            request=other, supplier=self.a, unit_price_rial=Decimal(1),
        )
        self.client.force_authenticate(self.manager)
        response = self.client.post(
            f"/api/commercial/requests/{self.req.id}/award/",
            {"quote": stray.id}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_ceo_may_not_award(self):
        self.client.force_authenticate(self.ceo)
        response = self.client.post(
            f"/api/commercial/requests/{self.req.id}/award/",
            {"quote": self.q_a.id}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_first_quote_moves_the_request_into_quoting(self):
        fresh = self._request()
        self.client.force_authenticate(self.manager)
        self.client.post("/api/commercial/quotes/", {
            "request": fresh.id, "supplier": self.a.id,
            "unit_price_rial": "900000",
        })
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, PurchaseRequest.Status.QUOTING)


class OrderTests(CommercialTestCase):
    def test_total_follows_its_parts(self):
        order = self._order(date(2026, 7, 25), 20, 950_000)
        self.assertEqual(order.total_rial, Decimal(19_000_000))
        order.quantity = Decimal(30)
        # Computed, never stored — a saved total would still read 19,000,000.
        self.assertEqual(order.total_rial, Decimal(28_500_000))

    def test_delivered_requires_a_date(self):
        order = self._order(date(2026, 7, 25), 5, 100, status="pending")
        self.client.force_authenticate(self.manager)
        response = self.client.patch(
            f"/api/commercial/orders/{order.id}/", {"status": "delivered"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("delivered_on", response.data)

    def test_cancelled_orders_leave_the_totals(self):
        self._order(date(2026, 7, 25), 10, 1_000_000)
        self._order(date(2026, 7, 26), 10, 1_000_000,
                    status=PurchaseOrder.Status.CANCELLED)
        self.client.force_authenticate(self.manager)
        report = self.client.get("/api/commercial/reports/purchases/").data
        self.assertEqual(report["totals"]["amount_rial"], "10000000")
        self.assertEqual(report["totals"]["order_count"], 1)
        # Reported rather than hidden, so a filtered view never looks like it
        # quietly lost rows.
        self.assertEqual(report["totals"]["cancelled_count"], 1)

    def test_orders_can_be_filtered_to_one_request(self):
        req = self._request()
        mine = PurchaseOrder.objects.create(
            request=req, supplier=self.a, material=self.shrink,
            quantity=Decimal(20), unit_price_rial=Decimal(950_000),
            ordered_on=date(2026, 7, 26),
        )
        self._order(date(2026, 7, 27), 5, 100)  # unrelated

        self.client.force_authenticate(self.manager)
        rows = self.client.get(
            "/api/commercial/orders/", {"request": req.id}
        ).data["results"]
        # An unfiltered filterset silently ignores the parameter rather than
        # erroring, so the استعلام page listed every order as if it owned them.
        self.assertEqual([r["id"] for r in rows], [mine.id])

    def test_material_in_use_cannot_be_deleted(self):
        self._order(date(2026, 7, 25), 10, 1_000)
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f"/api/commercial/materials/{self.shrink.id}/")
        self.assertEqual(response.status_code, 400)


class PriceHistoryTests(CommercialTestCase):
    def test_price_change_is_reported_between_the_last_two_months(self):
        self._order(date(2026, 6, 25), 10, 940_000)   # تیر
        self._order(date(2026, 7, 25), 10, 990_000)   # مرداد
        history = price_history.for_material(self.shrink)
        self.assertEqual(history["latest_rial"], "990000")
        self.assertEqual(history["previous_rial"], "940000")
        self.assertAlmostEqual(history["change_pct"], 5.319, places=2)

    def test_a_single_price_reports_no_change(self):
        self._order(date(2026, 7, 25), 10, 990_000)
        history = price_history.for_material(self.shrink)
        # Growth from nothing is a first purchase, not a percentage.
        self.assertIsNone(history["change_pct"])

    def test_paid_price_is_weighted_by_quantity(self):
        # Both inside Mordad 1405 (which opens 2026-07-23) — the weighting is
        # per month, so dates either side of a Jalali boundary would land in
        # different buckets and prove nothing.
        self._order(date(2026, 7, 25), 100, 900_000)
        self._order(date(2026, 7, 28), 2, 1_200_000)
        rows = [r for r in price_history.for_material(self.shrink)["rows"]
                if r["paid_rial"]]
        # A 2-roll rush buy must not drag the month's price to the midpoint of
        # the two figures; 100 rolls at 900k dominate.
        self.assertLess(Decimal(rows[-1]["paid_rial"]), Decimal(950_000))

    def test_losing_quotes_stay_in_the_history(self):
        req = self._request()
        Quote.objects.create(request=req, supplier=self.b,
                             unit_price_rial=Decimal(1_100_000),
                             quoted_on=date(2026, 7, 25))
        entries = price_history.for_material(self.shrink)["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["supplier"], "شرکت ب")
        self.assertFalse(entries[0]["is_selected"])


class SupplierStatsTests(CommercialTestCase):
    def test_win_rate_counts_quotes_not_orders(self):
        req = self._request()
        won = Quote.objects.create(request=req, supplier=self.a,
                                   unit_price_rial=Decimal(900_000))
        Quote.objects.create(request=req, supplier=self.b,
                             unit_price_rial=Decimal(950_000))
        won.is_selected = True
        won.save()

        second = self._request()
        Quote.objects.create(request=second, supplier=self.a,
                             unit_price_rial=Decimal(910_000))

        stats = supplier_stats.for_supplier(self.a)
        self.assertEqual(stats["quote_count"], 2)
        self.assertEqual(stats["win_count"], 1)
        self.assertEqual(stats["win_rate_pct"], 50.0)

    def test_a_supplier_with_no_quotes_has_no_win_rate(self):
        stats = supplier_stats.for_supplier(self.c)
        # Not 0% — that would sort a brand-new supplier below one that
        # genuinely loses every time.
        self.assertIsNone(stats["win_rate_pct"])

    def test_actual_lead_time_comes_from_the_dates(self):
        PurchaseOrder.objects.create(
            supplier=self.a, material=self.shrink, quantity=Decimal(1),
            unit_price_rial=Decimal(1000), ordered_on=date(2026, 7, 20),
            delivered_on=date(2026, 7, 24),
            status=PurchaseOrder.Status.DELIVERED,
        )
        self.assertEqual(supplier_stats.for_supplier(self.a)["avg_actual_days"], 4.0)


class ConsumptionTests(CommercialTestCase):
    def test_months_with_no_purchase_are_rows_not_gaps(self):
        self._order(date(2026, 4, 25), 10, 1_000)   # اردیبهشت
        self._order(date(2026, 7, 25), 10, 1_000)   # مرداد
        rows = consumption.monthly(self.shrink)["rows"]
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["has_data"] for r in rows], [True, False, False, True])

    def test_average_uses_only_the_months_that_have_data(self):
        self._order(date(2026, 4, 25), 100, 1_000)
        self._order(date(2026, 7, 25), 200, 1_000)
        data = consumption.monthly(self.shrink)
        # 150, not 75: the factory's monthly need is not diluted by the months
        # nobody bought in.
        self.assertEqual(Decimal(data["average_qty"]), Decimal("150.00"))


class ForecastTests(CommercialTestCase):
    def _rising(self):
        # Twelve consecutive months, climbing — the department's own example.
        quantities = [110, 120, 118, 130, 127, 135, 140, 138, 145, 150, 149, 152]
        day = date(2025, 9, 23)
        for i, qty in enumerate(quantities):
            month = day.month + i
            year = day.year + (month - 1) // 12
            self._order(date(year, (month - 1) % 12 + 1, 5), qty, 1_000_000)

    def test_a_rising_series_forecasts_above_the_last_month(self):
        self._rising()
        result = forecast.for_material(self.shrink, horizon=3)
        self.assertEqual(len(result["rows"]), 3)
        first = Decimal(result["rows"][0]["quantity"])
        self.assertGreater(first, Decimal(140))
        self.assertGreater(result["slope_per_month"], 0)
        # Twelve steady months is exactly the case that should read confident.
        self.assertIn(result["confidence_level"], {"high", "medium"})

    def test_forecast_grows_across_the_horizon_when_the_trend_does(self):
        self._rising()
        rows = forecast.for_material(self.shrink, horizon=3)["rows"]
        values = [Decimal(r["quantity"]) for r in rows]
        self.assertEqual(values, sorted(values))

    def test_no_history_answers_without_pretending(self):
        result = forecast.for_material(self.shrink, horizon=3)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["confidence_level"], "none")
        self.assertIn("پیش‌بینی", result["note"])

    def test_thin_history_falls_back_to_the_average(self):
        self._order(date(2026, 6, 25), 100, 1_000)
        self._order(date(2026, 7, 25), 300, 1_000)
        result = forecast.for_material(self.shrink, horizon=2)
        # Two points make a line that would forecast 500 next month. Refusing
        # the trend under six months is the whole point of the guard.
        self.assertEqual(result["slope_per_month"], 0.0)
        self.assertEqual(result["confidence_level"], "low")
        self.assertLess(Decimal(result["rows"][0]["quantity"]), Decimal(400))

    def test_forecast_never_goes_negative(self):
        # A steep decline extrapolates below zero within the horizon.
        for i, qty in enumerate([300, 250, 200, 150, 100, 60, 30, 10]):
            self._order(date(2026, 1 + i, 5), qty, 1_000)
        rows = forecast.for_material(self.shrink, horizon=6)["rows"]
        self.assertTrue(all(Decimal(r["quantity"]) >= 0 for r in rows))


class DashboardTests(CommercialTestCase):
    def test_dashboard_reports_this_month(self):
        self._order(date(2026, 7, 25), 20, 1_000_000)
        self.client.force_authenticate(self.manager)
        data = self.client.get(
            "/api/commercial/dashboard/", {"on": "2026-07-28"}
        ).data
        self.assertEqual(data["spend_rial"], "20000000")
        self.assertEqual(data["order_count"], 1)
        self.assertEqual(data["top_material"]["name"], "نوار شیرینگ")
        self.assertEqual(data["top_supplier"]["name"], "شرکت الف")
        self.assertTrue(data["can_edit"])

    def test_dashboard_is_read_only_for_the_ceo(self):
        self.client.force_authenticate(self.ceo)
        data = self.client.get("/api/commercial/dashboard/").data
        self.assertFalse(data["can_edit"])

    def test_empty_install_does_not_break(self):
        self.client.force_authenticate(self.manager)
        response = self.client.get("/api/commercial/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["top_material"])
