"""
تحلیل هوشمند — the written reading of a month, and «بپرس».

What must hold:

* **Who may use it.** CEO, administrators and managers; an operator is refused.
* **Nobody reads past their own section.** A sales manager's analysis is their
  channel's figures only, and it has no مالی section at all.
* **The sentences are true.** A drop is called a drop, the plan is read from
  «تعیین تارگت», and a question is answered from the same engine the boards
  use.
"""
from datetime import date
from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import Role, User
from apps.core.models import DimPeriod, PeriodKind
from apps.dashboards.ask import answer, parse
from apps.dashboards.insights import analyse
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactSalesMonthly,
    FactSalesProvince,
    SalesChannel,
    SalesTarget,
)

A = ApprovalStatus.APPROVED


def _user(username, role, department="") -> User:
    return User.objects.create_user(username=username, password="x", role=role,
                                    department=department)


def _fill(finding: dict) -> str:
    text = finding.get("text") or finding.get("answer")
    for key, num in finding["values"].items():
        text = text.replace("{" + key + "}", str(num["v"]))
    return text


class InsightsTests(APITestCase):
    def setUp(self):
        self.ceo = _user("ceo", Role.EXECUTIVE)
        self.op = _user("op", Role.OPERATOR, "sales_team")
        self.team_mgr = _user("tm", Role.MANAGER, "sales_team")
        # Months far in the past, so neither is «the running month».
        self.m1 = DimPeriod.objects.create(jalali_year=1403, jalali_month=5, kind=PeriodKind.MONTH,
                                           start_date=date(2024, 7, 22), end_date=date(2024, 8, 21))
        self.m2 = DimPeriod.objects.create(jalali_year=1403, jalali_month=6, kind=PeriodKind.MONTH,
                                           start_date=date(2024, 8, 22), end_date=date(2024, 9, 21))
        team = DimTeam.objects.create(code="t", name_fa="تیم یک")
        self.ali = DimEmployee.objects.create(code="ali", full_name_fa="علی رضایی", team=team)
        self.sara = DimEmployee.objects.create(code="sara", full_name_fa="سارا کریمی", team=team)
        self.tehran = DimProvince.objects.create(code="thr", name_fa="تهران")
        self.fars = DimProvince.objects.create(code="frs", name_fa="فارس")

        for period, ali, sara in ((self.m1, 1000, 1000), (self.m2, 900, 300)):
            FactSalesMonthly.objects.create(period=period, employee=self.ali, channel=SalesChannel.TEAM,
                                            revenue_rial=Decimal(ali), profit_rial=Decimal(ali // 5),
                                            status=A)
            FactSalesMonthly.objects.create(period=period, employee=self.sara, channel=SalesChannel.TEAM,
                                            revenue_rial=Decimal(sara), profit_rial=Decimal(sara // 5),
                                            status=A)
            for emp in (self.ali, self.sara):
                SalesTarget.objects.create(period=period, channel=SalesChannel.TEAM, employee=emp,
                                           target_rial=Decimal(1000))
        FactSalesProvince.objects.create(period=self.m1, province=self.tehran, channel=SalesChannel.TEAM,
                                         sales_rial=Decimal(1500), status=A)
        FactSalesProvince.objects.create(period=self.m2, province=self.tehran, channel=SalesChannel.TEAM,
                                         sales_rial=Decimal(600), status=A)
        FactSalesProvince.objects.create(period=self.m2, province=self.fars, channel=SalesChannel.TEAM,
                                         sales_rial=Decimal(600), status=A)
        # Another channel's sale: the CEO counts it, the team manager must not.
        FactSalesMonthly.objects.create(period=self.m2, employee=self.ali,
                                        channel=SalesChannel.ORGANIZATIONAL,
                                        revenue_rial=Decimal(5000), status=A)

    # -- access ------------------------------------------------------------
    def test_operator_is_refused(self):
        self.client.force_authenticate(self.op)
        self.assertEqual(self.client.get(reverse("dashboards-insights")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("dashboards-ask"), {"question": "فروش"}).status_code, 403)

    def test_manager_reads_own_channel_and_no_finance(self):
        result = analyse(self.team_mgr, self.m2.id)
        keys = [s["key"] for s in result["sections"]]
        self.assertEqual(keys, ["sales"])
        revenue = result["sections"][0]["stats"][0]["value"]["v"]
        self.assertEqual(revenue, 1200)  # 900 + 300, not the 5000 on the bank channel

    def test_ceo_sees_every_channel(self):
        sales = next(s for s in analyse(self.ceo, self.m2.id)["sections"] if s["key"] == "sales")
        self.assertEqual(sales["stats"][0]["value"]["v"], 6200)

    # -- the reading ---------------------------------------------------------
    def test_calls_the_drop_and_names_who_fell(self):
        sales = analyse(self.team_mgr, self.m2.id)["sections"][0]
        texts = [_fill(f) for f in sales["findings"]]
        self.assertTrue(any("فروش 1200.0 بود؛ 40.0 کاهش" in t for t in texts), texts)
        self.assertTrue(any("«سارا کریمی»" in t and "افت" in t for t in texts), texts)
        # 300 of a 1000 plan is under 60٪.
        self.assertTrue(any("کمتر از ۶۰٪ تارگت" in t and "سارا" in t for t in texts), texts)
        self.assertTrue(any(f["tone"] == "bad" for f in sales["findings"]))

    def test_empty_month_says_so(self):
        empty = DimPeriod.objects.create(jalali_year=1403, jalali_month=7, kind=PeriodKind.MONTH)
        sales = analyse(self.team_mgr, empty.id)["sections"][0]
        self.assertIn("ثبت نشده", sales["findings"][0]["text"])

    # -- بپرس ---------------------------------------------------------------
    def test_top_provinces(self):
        a = answer(self.team_mgr, "۲ استان با بیشترین فروش", self.m2.id)
        self.assertTrue(a["ok"])
        self.assertEqual(len(a["table"]["rows"]), 2)

    def test_named_province_and_month(self):
        a = answer(self.team_mgr, "فروش تهران در مرداد ۱۴۰۳", self.m2.id)
        self.assertIn("«تهران»", a["answer"])
        self.assertEqual(a["values"]["a"]["v"], 1500)

    def test_comparison_of_two_months(self):
        a = answer(self.team_mgr, "مقایسه فروش مرداد ۱۴۰۳ و شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual((a["values"]["a"]["v"], a["values"]["b"]["v"]), (2000, 1200))

    def test_lowest_target_achievement_ranks_by_achievement(self):
        a = answer(self.team_mgr, "کدام کارشناس کمترین تحقق تارگت را دارد؟", self.m2.id)
        self.assertIn("سارا کریمی", a["answer"])
        self.assertEqual(a["values"]["t"]["v"], 30)

    def test_word_inside_a_word_is_not_a_topic(self):
        # «تن» (tonnage) must not fire on «استان».
        p = parse("فروش استان تهران", self.m2, self.m1)
        self.assertEqual(p.topic.metric, "revenue")

    def test_manager_cannot_ask_about_finance(self):
        a = answer(self.team_mgr, "پرداخت‌ها در شهریور", self.m2.id)
        self.assertFalse(a["ok"])

    def test_nonsense_offers_examples(self):
        a = answer(self.team_mgr, "هوا چطوره؟", self.m2.id)
        self.assertFalse(a["ok"])
        self.assertTrue(a["suggestions"])


class ExamplesFollowAccessTests(APITestCase):
    """A production manager was offered sales questions they could not ask."""

    def test_production_manager_gets_no_sales_examples(self):
        from apps.dashboards.ask import examples_for

        DimPeriod.objects.create(jalali_year=1403, jalali_month=5, kind=PeriodKind.MONTH)
        prod = _user("pm", Role.MANAGER, "production")
        examples = examples_for(prod)
        self.assertTrue(examples)
        self.assertFalse(any("فروش" in q or "تارگت" in q or "پرداخت" in q for q in examples), examples)
        a = answer(prod, "هوا چطوره؟")
        self.assertNotIn("فروش", a["answer"])
        self.assertEqual(a["suggestions"], examples)
