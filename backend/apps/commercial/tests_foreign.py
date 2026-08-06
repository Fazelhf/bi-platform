"""
بازرگانی خارجی tests.

Almost everything here is a clock. The module's whole value is that «۲۹۵ روز»
is computed rather than retyped, so these tests pin the counting: when it
starts, when it stops, and what happens at the boundaries where a wrong answer
would cost real money — the day Free Days run out, the day an allocation
lands, the day a file is closed.

Every test passes an explicit `today`. A test that used the real date would
pass in August and fail in September.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.commercial.models import (
    Bank,
    Currency,
    ForeignOrder,
    FxRate,
    OrderEvent,
    RateKind,
    Shipment,
    Supplier,
)
from apps.commercial.services import (
    allocation_queue,
    demurrage,
    foreign_alerts,
    foreign_dashboard,
    fx,
    stalled,
)

User = get_user_model()
TODAY = date(2026, 8, 5)


def mk_user(username, role, department):
    return User.objects.create_user(
        username=username, password="x", role=role, department=department
    )


class ForeignBase(APITestCase):
    def setUp(self):
        # One بازرگانی department covering both halves — the same manager runs
        # domestic buying and the import desk.
        self.manager = mk_user("sadaf", "manager", "commercial")
        self.ceo = mk_user("ceo2", "executive", "")
        self.sales = mk_user("smgr", "manager", "sales_team")

        self.karafarin = Bank.objects.create(code="k", name_fa="کارآفرین", sort_order=1)
        self.melli = Bank.objects.create(code="m", name_fa="ملی", sort_order=2)
        self.seller = Supplier.objects.create(
            code="op", name_fa="اورینتال", origin=Supplier.Origin.FOREIGN,
            country="چین",
        )

    def mk_order(self, **kw):
        defaults = dict(
            pi_no="FP2500001TK-01RM",
            supplier=self.seller,
            bank=self.karafarin,
            currency=Currency.USD,
            amount=Decimal("98000"),
            weight_ton=Decimal("50"),
            goods_desc="کاغذ حرارتی ۵۵ گرم",
            registered_on=date(2026, 1, 10),
            status=ForeignOrder.Status.QUEUED,
        )
        return ForeignOrder.objects.create(**{**defaults, **kw})

    def mk_shipment(self, order, **kw):
        defaults = dict(
            container_no="MIOU4393002",
            weight_ton=Decimal("25"),
            status=Shipment.Status.AT_PORT,
            free_days=10,
            demurrage_daily_rial=Decimal("50000000"),
            storage_daily_rial=Decimal("10000000"),
        )
        return Shipment.objects.create(order=order, **{**defaults, **kw})


class QueueTests(ForeignBase):
    def test_waiting_days_stop_on_the_day_allocation_landed(self):
        order = self.mk_order(
            queued_on=date(2026, 1, 20), allocated_on=date(2026, 3, 1)
        )
        # 40 days, not "since January" — a file allocated months ago must not
        # report a growing wait and swamp the ones actually stuck.
        self.assertEqual(order.days_in_queue(TODAY), 40)
        self.assertFalse(order.is_waiting_allocation)

    def test_still_waiting_counts_up_to_today(self):
        order = self.mk_order(queued_on=date(2026, 7, 6))
        self.assertEqual(order.days_in_queue(TODAY), 30)
        self.assertTrue(order.is_waiting_allocation)

    def test_settled_file_leaves_the_queue_even_without_an_allocation_date(self):
        order = self.mk_order(
            queued_on=date(2026, 1, 1), status=ForeignOrder.Status.CANCELLED
        )
        self.assertFalse(order.is_waiting_allocation)
        self.assertEqual(allocation_queue.build(TODAY)["totals"]["count"], 0)

    def test_bank_shares_are_by_file_count_and_sum_to_a_hundred(self):
        for _ in range(3):
            self.mk_order(queued_on=date(2026, 7, 1), bank=self.karafarin)
        self.mk_order(queued_on=date(2026, 7, 1), bank=self.melli)

        report = allocation_queue.build(TODAY)
        shares = {r["name"]: r["share_pct"] for r in report["by_bank"]}
        self.assertEqual(shares["کارآفرین"], 75.0)
        self.assertEqual(shares["ملی"], 25.0)
        self.assertEqual(round(sum(shares.values())), 100)

    def test_a_file_with_no_bank_is_reported_not_dropped(self):
        self.mk_order(queued_on=date(2026, 7, 1), bank=None)
        report = allocation_queue.build(TODAY)
        names = [r["name"] for r in report["by_bank"]]
        # Silently excluding it would make the shares add up to 100% of a
        # total that is not the real total.
        self.assertIn("بانک ثبت نشده", names)
        self.assertEqual(report["totals"]["count"], 1)

    def test_overdue_is_measured_against_the_banks_own_promise(self):
        self.mk_order(queued_on=date(2026, 7, 1), expected_queue_days=90)
        self.mk_order(queued_on=date(2026, 7, 1), expected_queue_days=10)
        report = allocation_queue.build(TODAY)
        self.assertEqual(report["totals"]["overdue_count"], 1)


class StalledTests(ForeignBase):
    def test_idle_days_run_from_the_last_event_not_the_status(self):
        order = self.mk_order(registered_on=date(2026, 1, 1))
        OrderEvent.objects.create(
            order=order, at=date(2026, 7, 30), title="پیگیری تلفنی با بانک"
        )
        # Six days, not seven months: someone is chasing this file weekly.
        self.assertEqual(order.idle_days(TODAY), 6)
        self.assertEqual(stalled.level_for(order.idle_days(TODAY)), "ok")

    def test_with_no_events_it_falls_back_to_the_gate_dates(self):
        order = self.mk_order(registered_on=date(2026, 6, 1), queued_on=date(2026, 7, 20))
        self.assertEqual(order.idle_days(TODAY), 16)

    def test_bands(self):
        self.assertEqual(stalled.level_for(0), "ok")
        self.assertEqual(stalled.level_for(14), "ok")
        self.assertEqual(stalled.level_for(15), "warn")
        self.assertEqual(stalled.level_for(29), "warn")
        self.assertEqual(stalled.level_for(30), "danger")

    def test_a_closed_file_is_never_stalled(self):
        self.mk_order(
            registered_on=date(2025, 1, 1), status=ForeignOrder.Status.CLOSED
        )
        report = stalled.build(today=TODAY)
        self.assertEqual(report["rows"], [])


class DemurrageTests(ForeignBase):
    def test_nothing_accrues_before_the_free_days_run_out(self):
        order = self.mk_order()
        s = self.mk_shipment(order, arrived_on=date(2026, 8, 1), free_days=10)
        self.assertEqual(s.days_at_port(TODAY), 4)
        self.assertEqual(s.free_days_left(TODAY), 6)
        self.assertEqual(s.demurrage_days(TODAY), 0)
        self.assertEqual(s.demurrage_rial(TODAY), Decimal(0))

    def test_demurrage_starts_only_past_the_free_days(self):
        order = self.mk_order()
        s = self.mk_shipment(order, arrived_on=date(2026, 7, 20), free_days=10)
        # 16 days at port, 10 free → 6 charged.
        self.assertEqual(s.days_at_port(TODAY), 16)
        self.assertEqual(s.demurrage_days(TODAY), 6)
        self.assertEqual(s.demurrage_rial(TODAY), Decimal("300000000"))

    def test_storage_runs_from_arrival_not_from_the_free_day_boundary(self):
        order = self.mk_order()
        s = self.mk_shipment(order, arrived_on=date(2026, 7, 20), free_days=10)
        # Free Days are the line's container allowance; the port charges rent
        # from day one. Netting them would make Free Days look protective.
        self.assertEqual(s.storage_rial(TODAY), Decimal("160000000"))

    def test_the_clock_stops_at_clearance(self):
        order = self.mk_order()
        s = self.mk_shipment(
            order, arrived_on=date(2026, 6, 1), cleared_on=date(2026, 6, 21),
            free_days=10, status=Shipment.Status.CLEARED,
        )
        self.assertEqual(s.days_at_port(TODAY), 20)
        self.assertEqual(s.demurrage_days(TODAY), 10)
        self.assertFalse(s.is_accruing)

    def test_a_container_that_never_arrived_costs_nothing(self):
        order = self.mk_order()
        s = self.mk_shipment(
            order, arrived_on=None, status=Shipment.Status.AT_SEA
        )
        self.assertIsNone(s.days_at_port(TODAY))
        self.assertEqual(s.accruing_rial(TODAY), Decimal(0))
        self.assertEqual(demurrage.build(today=TODAY)["rows"], [])

    def test_daily_burn_counts_only_containers_still_ticking(self):
        order = self.mk_order()
        self.mk_shipment(order, arrived_on=date(2026, 7, 1), free_days=5)
        self.mk_shipment(
            order, container_no="X2", arrived_on=date(2026, 6, 1),
            cleared_on=date(2026, 6, 10), status=Shipment.Status.CLEARED,
        )
        totals = demurrage.build(today=TODAY)["totals"]
        self.assertEqual(totals["container_count"], 2)
        self.assertEqual(totals["accruing_count"], 1)
        self.assertEqual(Decimal(totals["daily_burn_rial"]), Decimal("60000000"))


class FxTests(ForeignBase):
    def test_latest_for_uses_the_most_recent_rate_at_or_before_the_date(self):
        FxRate.objects.create(
            currency=Currency.USD, kind=RateKind.CENTRE,
            on_date=date(2026, 8, 1), rate_rial=Decimal("700000"),
        )
        FxRate.objects.create(
            currency=Currency.USD, kind=RateKind.CENTRE,
            on_date=date(2026, 8, 10), rate_rial=Decimal("710000"),
        )
        # Nobody publishes a rate on a Friday; a report for Friday must not
        # show zero.
        found = FxRate.latest_for(Currency.USD, RateKind.CENTRE, TODAY)
        self.assertEqual(found.rate_rial, Decimal("700000"))

    def test_the_three_kinds_are_kept_apart(self):
        for kind, value in (
            (RateKind.FREE, "1100000"),
            (RateKind.CENTRE, "700000"),
            (RateKind.CUSTOMS, "550000"),
        ):
            FxRate.objects.create(
                currency=Currency.USD, kind=kind,
                on_date=date(2026, 8, 1), rate_rial=Decimal(value),
            )
        order = self.mk_order(amount=Decimal("100"))
        self.assertEqual(
            order.amount_rial(RateKind.CUSTOMS, TODAY), Decimal("55000000")
        )
        self.assertEqual(
            order.amount_rial(RateKind.FREE, TODAY), Decimal("110000000")
        )

    def test_missing_rate_returns_none_rather_than_zero(self):
        order = self.mk_order(amount=Decimal("100"))
        # Zero would silently value the whole file at nothing.
        self.assertIsNone(order.amount_rial(RateKind.CENTRE, TODAY))

    def test_sync_without_a_provider_reports_instead_of_failing(self):
        report = fx.sync(TODAY)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "no_provider")
        self.assertEqual(report["written"], 0)
        self.assertEqual(len(report["missing"]), 6)

    def test_board_says_how_old_each_rate_is(self):
        FxRate.objects.create(
            currency=Currency.USD, kind=RateKind.FREE,
            on_date=date(2026, 7, 26), rate_rial=Decimal("1100000"),
        )
        row = next(
            r for r in fx.board(TODAY)
            if r["currency"] == "USD" and r["kind"] == "free"
        )
        self.assertEqual(row["age_days"], 10)


class AlertTests(ForeignBase):
    def test_a_passed_deadline_is_a_danger(self):
        self.mk_order(valid_until=date(2026, 7, 1))
        kinds = [a["kind"] for a in foreign_alerts.build(TODAY)]
        self.assertIn("deadline_passed", kinds)

    def test_free_days_about_to_end_warns_before_it_costs_anything(self):
        order = self.mk_order()
        self.mk_shipment(order, arrived_on=date(2026, 7, 28), free_days=10)
        alerts = foreign_alerts.build(TODAY)
        self.assertIn("free_days_ending", [a["kind"] for a in alerts])

    def test_settled_files_raise_nothing(self):
        self.mk_order(
            valid_until=date(2026, 1, 1), status=ForeignOrder.Status.CLOSED
        )
        self.assertEqual(foreign_alerts.build(TODAY), [])


class ForeignPermissionTests(ForeignBase):
    def test_foreign_writes_ceo_reads_sales_gets_nothing(self):
        payload = {
            "pi_no": "TEST-1", "currency": "USD", "amount": "1000",
            "registered_on": "2026-08-01",
        }

        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.post("/api/commercial/foreign/orders/", payload).status_code, 201
        )

        self.client.force_authenticate(self.ceo)
        self.assertEqual(
            self.client.get("/api/commercial/foreign/dashboard/").status_code, 200
        )
        self.assertEqual(
            self.client.post("/api/commercial/foreign/orders/", payload).status_code, 403
        )

        self.client.force_authenticate(self.sales)
        # Supplier prices and import costs are commercially sensitive.
        self.assertEqual(
            self.client.get("/api/commercial/foreign/dashboard/").status_code, 403
        )
        self.assertEqual(
            self.client.get("/api/commercial/foreign/queue/").status_code, 403
        )

    def test_one_department_opens_both_halves(self):
        self.client.force_authenticate(self.manager)
        # بازرگانی is one department doing two jobs. Splitting it would mean
        # the manager's account could hold only one of them at a time.
        for path in (
            "/api/commercial/dashboard/",
            "/api/commercial/foreign/dashboard/",
            "/api/commercial/foreign/cards/",
            "/api/commercial/foreign/payments/",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)


class ForeignApiTests(ForeignBase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.manager)

    def test_file_numbers_are_not_reused_after_a_delete(self):
        a = self.mk_order()
        first = a.file_no
        a.delete()
        b = self.mk_order()
        self.assertNotEqual(first, b.file_no)

    def test_status_change_lands_on_the_timeline(self):
        order = self.mk_order()
        self.client.patch(
            f"/api/commercial/foreign/orders/{order.id}/",
            {"status": ForeignOrder.Status.ALLOCATED}, format="json",
        )
        # Otherwise moving a file forward would leave it looking abandoned.
        self.assertTrue(order.events.exists())
        self.assertEqual(order.idle_days(TODAY), 0)

    def test_clearing_before_arrival_is_refused(self):
        order = self.mk_order()
        response = self.client.post("/api/commercial/foreign/shipments/", {
            "order": order.id, "arrived_on": "2026-07-20",
            "cleared_on": "2026-07-10", "status": "cleared",
        }, format="json")
        # A negative days-at-port would produce a negative demurrage bill and
        # quietly reduce the totals.
        self.assertEqual(response.status_code, 400)
        self.assertIn("cleared_on", response.data)

    def test_a_zero_fx_rate_is_refused(self):
        response = self.client.post("/api/commercial/foreign/fx-rates/", {
            "currency": "USD", "kind": "centre",
            "on_date": "2026-08-01", "rate_rial": 0,
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_dashboard_reports_each_currency_separately(self):
        self.mk_order(currency=Currency.USD, amount=Decimal("1000"))
        self.mk_order(currency=Currency.EUR, amount=Decimal("500"))
        data = foreign_dashboard.build(TODAY)
        codes = {r["currency"]: r["amount"] for r in data["value_by_currency"]}
        # Summing dollars and euros needs a rate, and which of the three is a
        # choice no headline figure should make silently.
        self.assertEqual(codes["USD"], "1000.00")
        self.assertEqual(codes["EUR"], "500.00")
