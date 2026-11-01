"""تولید روزانه: a holiday is a holiday, a working day with no entry is a gap."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod
from apps.office.models_calendar import Holiday
from apps.production.models import DimMachine, FactProduction


class DailyProductionTests(APITestCase):
    def setUp(self):
        # Mehr 1405: 1 Mehr = 23 Sep 2026 (چهارشنبه).
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=7, kind="month",
                                              start_date=date(2026, 9, 23), end_date=date(2026, 10, 22))
        self.cut = DimMachine.objects.create(code="d-cut", name_fa="برش ۱", sort_order=1)
        self.d1 = DimPeriod.objects.create(jalali_year=1405, jalali_month=7, kind="day", parent=self.month,
                                           start_date=date(2026, 9, 23), end_date=date(2026, 9, 23))
        for shift, out in (("day", 100), ("night", 60)):
            FactProduction.objects.create(period=self.d1, machine=self.cut, shift=shift,
                                          output_units=Decimal(out), active_shifts=Decimal(1))
        Holiday.objects.create(date=date(2026, 9, 26), title="تعطیل رسمی")  # شنبه
        from apps.core.models import PeriodGrain

        PeriodGrain.objects.update_or_create(month=self.month, department="production", defaults={"grain": "day"})
        user = get_user_model().objects.create_user(username="d-ceo", password="pw12345!", role="executive")
        self.client.force_authenticate(user)

    def test_days_marked_and_totals(self):
        res = self.client.get("/api/production/dashboard/daily/", {"month": self.month.pk, "day": self.d1.pk})
        self.assertEqual(res.status_code, 200, res.data)
        days = {d["date"]: d for d in res.data["days"]}
        first = days["2026-09-23"]
        self.assertEqual((first["output"], first["day_shift"], first["night_shift"], first["missing"]), (160, 100, 60, False))
        self.assertEqual((days["2026-09-26"]["workday"], days["2026-09-26"]["off"], days["2026-09-26"]["missing"]),
                         (False, "تعطیل رسمی", False))
        self.assertEqual(days["2026-09-24"]["off"], "تعطیل هفتگی")  # پنج‌شنبه
        self.assertTrue(days["2026-09-27"]["missing"])  # یکشنبه, worked, nothing entered
        self.assertEqual(res.data["summary"]["per_shift"], 80)
        self.assertEqual(len(res.data["detail"]), 2)
