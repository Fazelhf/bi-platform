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


class WhyAndFollowUpTests(InsightsTests):
    """«چرا؟» splits a change into who made it; a follow-up keeps what it omits."""

    def test_why_names_who_the_fall_came_from(self):
        a = answer(self.team_mgr, "چرا فروش شهریور ۱۴۰۳ افت کرد؟", self.m2.id)
        text = _fill(a)
        # 2000 → 1200: Sara's 700 of the 800 fall is 87.5٪ of it.
        self.assertIn("کاهش", text)
        self.assertIn("«سارا کریمی» (700", text)
        self.assertEqual(a["table"]["columns"][0], "کارشناس")

    def test_follow_up_keeps_measure_and_month(self):
        first = answer(self.team_mgr, "فروش تهران در شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual(first["values"]["a"]["v"], 600)
        second = answer(self.team_mgr, "فارس چطور؟", self.m2.id, context=first["context"])
        self.assertIn("«فارس»", second["answer"])
        self.assertEqual(second["values"]["a"]["v"], 600)
        third = answer(self.team_mgr, "تهران ماه قبلش؟", self.m2.id, context=second["context"])
        self.assertEqual(third["values"]["a"]["v"], 1500)

    def test_province_named_after_a_month_is_not_a_month(self):
        DimProvince.objects.create(code="az", name_fa="آذربایجان غربی")
        p = parse("فروش آذربایجان غربی", self.m2, self.m1)
        self.assertEqual(p.months, [])

    def test_inherited_breakdown_dropped_when_it_does_not_fit(self):
        first = answer(self.team_mgr, "فروش به تفکیک استان در شهریور ۱۴۰۳", self.m2.id)
        second = answer(self.team_mgr, "سود چی؟", self.m2.id, context=first["context"])
        self.assertTrue(second["ok"], second["answer"])
        self.assertEqual(second["values"]["a"]["v"], 240)  # 180 + 60


class LooseQuestionTests(InsightsTests):
    """Typos, seasons and a bare year — the way questions are actually typed."""

    def test_typo_in_a_province_is_read_and_said(self):
        a = answer(self.team_mgr, "هران شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 600)
        self.assertIn("«هران» را «تهران» خواندم", a["understood"])

    def test_digits_are_never_guessed(self):
        from apps.dashboards.ask import _near
        self.assertIsNone(_near("برش ۱", "برش ۲"))

    def test_season_adds_its_months(self):
        # تابستان ۱۴۰۳ = تیر..شهریور; only مرداد and شهریور exist here.
        a = answer(self.team_mgr, "فروش تهران تابستان ۱۴۰۳", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 2100)

    def test_bare_year(self):
        a = answer(self.team_mgr, "فروش ۱۴۰۳", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 3200)  # 2000 + 1200

    def test_every_answer_offers_what_to_ask_next(self):
        a = answer(self.team_mgr, "فروش شهریور ۱۴۰۳", self.m2.id)
        self.assertIn("چرا؟", a["suggestions"])
        follow = answer(self.team_mgr, a["suggestions"][0], self.m2.id, context=a["context"])
        self.assertTrue(follow["ok"], follow["answer"])


class SwearReplyTests(InsightsTests):
    """Management's call: swearing at the box gets sworn back at."""

    def test_kir_gets_to_dahanet(self):
        self.assertEqual(answer(self.team_mgr, "کیرم تو این سیستم")["answer"], "تو دهنت")

    def test_other_swears(self):
        self.assertEqual(answer(self.team_mgr, "جاکش")["answer"], "خودتی کصکش")

    def test_ordinary_words_that_contain_a_swear_are_not_swears(self):
        for q in ("فروش کسی بالا رفت؟", "کسب و کار", "گه گاهی فروش"):
            self.assertNotIn(answer(self.team_mgr, q, self.m2.id)["answer"],
                             ("تو دهنت", "خودتی کصکش"), q)


class SmarterReadingTests(InsightsTests):
    """A year ago, the season, records, pace — and the questions that go with them."""

    def setUp(self):
        super().setUp()
        # A year back: مرداد ۱۴۰۲ 1000 → شهریور ۱۴۰۲ 600, the same 40٪ fall as this year.
        self.ly5 = DimPeriod.objects.create(jalali_year=1402, jalali_month=5, kind=PeriodKind.MONTH,
                                            start_date=date(2023, 7, 23), end_date=date(2023, 8, 22))
        self.ly6 = DimPeriod.objects.create(jalali_year=1402, jalali_month=6, kind=PeriodKind.MONTH,
                                            start_date=date(2023, 8, 23), end_date=date(2023, 9, 22))
        for period, amount in ((self.ly5, 1000), (self.ly6, 600)):
            FactSalesMonthly.objects.create(period=period, employee=self.ali, channel=SalesChannel.TEAM,
                                            revenue_rial=Decimal(amount), status=A)

    # -- the reading ---------------------------------------------------------
    def test_a_fall_last_year_also_had_is_called_seasonal(self):
        texts = [_fill(f) for f in analyse(self.team_mgr, self.m2.id)["sections"][0]["findings"]]
        self.assertTrue(any("همین ماه سال قبل (600.0) 100.0 افزایش" in t for t in texts), texts)
        self.assertTrue(any("احتمالاً فصلی" in t for t in texts), texts)

    def test_a_fall_last_year_did_not_have_is_flagged(self):
        FactSalesMonthly.objects.filter(period=self.ly6).update(revenue_rial=Decimal(1500))
        texts = [_fill(f) for f in analyse(self.team_mgr, self.m2.id)["sections"][0]["findings"]]
        self.assertTrue(any("فصلی نیست" in t for t in texts), texts)

    def test_record_and_unusual_swing(self):
        from apps.dashboards.insights import _unusual

        record = _unusual([10, 11, 12, 10, 11, 30], "فروش", "rial")
        self.assertEqual(record[0].tone, "good")
        self.assertIn("بالاترین", record[0].text)
        swing = _unusual([0, 100] + [50] * 10 + [5], "فروش", "rial")
        self.assertEqual(swing[0].tone, "bad")
        self.assertIn("خارج از نوسان معمول", swing[0].text)
        self.assertEqual(_unusual([10, 12, 11, 10, 12, 11], "فروش", "rial"), [])

    def test_pace_projects_the_month_against_its_plan(self):
        from apps.dashboards.insights import _pace

        f = _pace((10, 30), 100, "فروش", "rial", target=400)  # 300 of 400 → 75٪
        self.assertEqual(f.tone, "bad")
        self.assertEqual(f.values["p"]["v"], 75)
        self.assertIsNone(_pace((3, 30), 100, "فروش", "rial", target=400))  # too early to say

    # -- بپرس ---------------------------------------------------------------
    def test_margin_is_a_ratio(self):
        a = answer(self.team_mgr, "حاشیه سود شهریور ۱۴۰۳", self.m2.id)
        self.assertTrue(a["ok"], a["answer"])
        self.assertEqual(a["values"]["a"], {"v": 20.0, "unit": "percent"})  # 240 / 1200

    def test_margin_by_person(self):
        a = answer(self.team_mgr, "حاشیه سود به تفکیک کارشناس شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual({r[1]["v"] for r in a["table"]["rows"]}, {20.0})

    def test_two_provinces_side_by_side(self):
        a = answer(self.team_mgr, "فروش تهران و فارس در شهریور ۱۴۰۳", self.m2.id)
        self.assertTrue(a["ok"], a["answer"])
        self.assertEqual(len(a["table"]["rows"]), 2)
        self.assertIn("«تهران»", a["answer"])
        self.assertIn("«فارس»", a["answer"])

    def test_one_number_carries_last_year(self):
        a = answer(self.team_mgr, "فروش شهریور ۱۴۰۳", self.m2.id)
        self.assertIn("همین ماه پارسال", a["answer"])
        self.assertEqual(a["values"]["ya"]["v"], 600)

    def test_same_month_last_year_and_against_it(self):
        a = answer(self.team_mgr, "فروش همین ماه پارسال", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 600)
        b = answer(self.team_mgr, "فروش این ماه نسبت به پارسال", self.m2.id)
        self.assertEqual((b["values"]["a"]["v"], b["values"]["b"]["v"]), (600, 1200))
        c = answer(self.team_mgr, "فروش پارسال", self.m2.id)
        self.assertEqual(c["values"]["a"]["v"], 1600)  # all of 1402 there is

    # -- the log -------------------------------------------------------------
    def test_questions_are_logged_and_misses_shown_to_admins(self):
        from apps.dashboards.models import AskLog

        self.client.force_authenticate(self.team_mgr)
        self.client.post(reverse("dashboards-ask"), {"question": "هوا چطوره؟"}, format="json")
        self.client.post(reverse("dashboards-ask"), {"question": "هوا چطوره؟"}, format="json")
        self.client.post(reverse("dashboards-ask"), {"question": "فروش"}, format="json")
        self.assertEqual(AskLog.objects.count(), 3)
        self.assertEqual(self.client.get(reverse("dashboards-ask-log")).status_code, 403)

        admin = User.objects.create_superuser("root", password="x")
        self.client.force_authenticate(admin)
        data = self.client.get(reverse("dashboards-ask-log")).data
        self.assertEqual((data["total"], data["understood"]), (3, 1))
        self.assertEqual(data["missed"][0]["question"], "هوا چطوره؟")
        self.assertEqual(data["missed"][0]["times"], 2)


class NamesAndChannelsTests(InsightsTests):
    """A salesperson by first name or surname; a sales department by its name."""

    def test_first_name_alone(self):
        a = answer(self.team_mgr, "فروش سارا شهریور ۱۴۰۳", self.m2.id)
        self.assertIn("«سارا کریمی»", a["answer"])
        self.assertEqual(a["values"]["a"]["v"], 300)

    def test_surname_alone(self):
        a = answer(self.team_mgr, "فروش رضایی شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 900)

    def test_a_shared_first_name_is_asked_about(self):
        DimEmployee.objects.create(code="ali2", full_name_fa="علی احمدی")
        a = answer(self.team_mgr, "فروش علی شهریور ۱۴۰۳", self.m2.id)
        self.assertFalse(a["ok"])
        self.assertIn("منظورتان کدام است", a["answer"])
        self.assertIn("فروش علی رضایی شهریور 1403", a["suggestions"])
        b = answer(self.team_mgr, a["suggestions"][0], self.m2.id)
        self.assertTrue(b["ok"], b["answer"])

    def test_channel_by_name(self):
        a = answer(self.ceo, "فروش بانکی شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual(a["values"]["a"]["v"], 5000)
        self.assertIn("«فروش بانکی»", a["answer"])
        b = answer(self.ceo, "فروش همکار شهریور ۱۴۰۳", self.m2.id)
        self.assertEqual(b["values"]["a"]["v"], 1200)

    def test_another_departments_channel_is_refused(self):
        a = answer(self.team_mgr, "فروش بانکی شهریور ۱۴۰۳", self.m2.id)
        self.assertFalse(a["ok"])
        self.assertIn("دسترسی ندارید", a["answer"])
