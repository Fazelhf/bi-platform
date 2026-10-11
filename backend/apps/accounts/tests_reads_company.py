"""
The finance manager reads the whole company — and only reads it.

Budget and cash are made of sales, production and بازرگانی, so the manager
of finance sees those sections the way the CEO does. Their finance
operators do not, and nobody gains a write.
"""
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.commercial.permissions import can_read_commercial, is_commercial
from apps.sales.views import assert_channel_visible


class ReadsCompanyTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("fin_mgr", password="x", role="manager", department="finance")
        self.operator = User.objects.create_user("fin_op", password="x", role="operator", department="finance")
        self.sales = User.objects.create_user("sales_mgr", password="x", role="manager", department="sales_team")

    def test_only_the_finance_manager_and_the_ceo_read_the_company(self):
        ceo = User.objects.create_user("ceo", password="x", role="executive")
        self.assertTrue(self.manager.reads_company)
        self.assertTrue(ceo.reads_company)
        self.assertFalse(self.operator.reads_company)
        self.assertFalse(self.sales.reads_company)

    def test_reads_every_sales_channel_and_commercial(self):
        for channel in ("team", "organizational", "b2b"):
            assert_channel_visible(self.manager, channel)  # no exception
        with self.assertRaises(PermissionDenied):
            assert_channel_visible(self.operator, "organizational")
        self.assertTrue(can_read_commercial(self.manager))
        self.assertFalse(can_read_commercial(self.operator))

    def test_reading_is_not_writing(self):
        self.assertFalse(is_commercial(self.manager))
        self.assertFalse(self.manager.owns_department("sales_team"))
