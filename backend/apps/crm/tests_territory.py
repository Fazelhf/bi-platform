"""Sales roster, province/zone responsibilities, Tehran's zones and the map's colour scale."""
from datetime import date

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import reports as rpt
from apps.crm.models import Customer, SalesInvoice, SalesZone, TerritoryAssignment
from apps.sales.models import DimEmployee, DimProvince, EmployeeChannel, SalesChannel


def _user(username, role="manager", department="sales_team"):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


def _customer(code, **kw):
    return Customer.objects.create(code=code, name_fa=code, first_contact_at=timezone.now(), **kw)


class RosterTests(APITestCase):
    def setUp(self):
        self.seller = DimEmployee.objects.create(code="r-s", full_name_fa="فروشنده")
        EmployeeChannel.objects.create(employee=self.seller, channel=SalesChannel.TEAM)
        self.accountant = DimEmployee.objects.create(code="r-a", full_name_fa="حسابدار")
        self.leaver = DimEmployee.objects.create(code="r-l", full_name_fa="رفته از فروش")
        self.old = _customer("r-c", owner=self.leaver)

    def test_the_ceo_picks_only_from_sales_staff(self):
        self.client.force_authenticate(_user("r-ceo", "executive", ""))
        emps = {e["id"]: e for e in self.client.get("/api/crm/options/").data["employees"]}
        self.assertTrue(emps[self.seller.pk]["active"])
        self.assertNotIn(self.accountant.pk, emps)
        # Owns an old customer: listed so the label shows, but not offered.
        self.assertFalse(emps[self.leaver.pk]["active"])

    def test_a_new_owner_off_the_roster_is_refused_but_an_old_one_is_kept(self):
        self.client.force_authenticate(_user("r-boss"))
        res = self.client.patch(f"/api/crm/customers/{self.old.pk}/", {"owner": self.accountant.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("owner", res.data)
        res = self.client.patch(f"/api/crm/customers/{self.old.pk}/",
                                {"owner": self.leaver.pk, "city": "قم"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        res = self.client.patch(f"/api/crm/customers/{self.old.pk}/", {"owner": self.seller.pk}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_bulk_assign_refuses_someone_off_the_roster(self):
        self.client.force_authenticate(_user("r-boss2"))
        res = self.client.post("/api/crm/customers/bulk-assign/",
                               {"ids": [self.old.pk], "owner": self.leaver.pk}, format="json")
        self.assertEqual(res.status_code, 400)


class TerritoryTests(APITestCase):
    def setUp(self):
        self.fars = DimProvince.objects.create(code="t-fars", name_fa="فارس")
        self.tehran = DimProvince.objects.create(code="t-thr", name_fa="تهران")
        self.a = DimEmployee.objects.create(code="t-a", full_name_fa="الف")
        self.b = DimEmployee.objects.create(code="t-b", full_name_fa="ب")
        for e in (self.a, self.b):
            EmployeeChannel.objects.create(employee=e, channel=SalesChannel.TEAM)
        self.outsider = DimEmployee.objects.create(code="t-o", full_name_fa="بیرونی")
        self.boss = _user("t-boss")
        self.client.force_authenticate(self.boss)

    def _assign(self, emp, role="expert", province=None, zone=None):
        return self.client.post("/api/crm/territories/", {
            "province": (province or self.fars).pk, "employee": emp.pk, "role": role,
            **({"zone": zone.pk} if zone else {}),
        }, format="json")

    def test_assign_manager_and_experts_and_replace_the_manager(self):
        self.assertEqual(self._assign(self.a, "manager").status_code, 201)
        self.assertEqual(self._assign(self.b, "expert").status_code, 201)
        self.assertEqual(self._assign(self.b, "manager").status_code, 201)
        managers = TerritoryAssignment.objects.filter(province=self.fars, role="manager")
        self.assertEqual(list(managers.values_list("employee", flat=True)), [self.b.pk])

    def test_only_roster_members_and_only_managers(self):
        self.assertEqual(self._assign(self.outsider).status_code, 400)
        self.client.force_authenticate(_user("t-op", "operator"))
        self.assertEqual(self._assign(self.a).status_code, 403)

    def test_geo_lists_assignees_and_splits_reps_without_double_counting(self):
        self._assign(self.a, "expert")
        cust = _customer("t-c", province=self.fars)
        SalesInvoice.objects.create(code="t-i1", number="1", customer=cust, owner=self.a,
                                    issued_at=date.today(), amount_rial=100)
        SalesInvoice.objects.create(code="t-i2", number="2", customer=cust, owner=self.b,
                                    issued_at=date.today(), amount_rial=50)
        f = rpt.Filters.from_query({"date_from": "2000-01-01"})
        row = next(r for r in rpt.geo_overview(f)["rows"] if r["id"] == self.fars.pk)
        self.assertEqual([e["id"] for e in row["experts"]], [self.a.pk])
        detail = rpt.geo_province(f, self.fars.pk)
        self.assertEqual([(r["id"], r["assigned"]) for r in detail["reps"]], [(self.a.pk, True), (self.b.pk, False)])
        self.assertEqual(sum(r["amount"] for r in detail["reps"]), detail["amount"])

    def test_tehran_zones_count_unplaced_customers_under_other_areas(self):
        SalesZone.ensure_tehran()
        bazar = SalesZone.objects.get(code="thr-bazar")
        c1 = _customer("t-z1", province=self.tehran, zone=bazar)
        c2 = _customer("t-z2", province=self.tehran)
        for i, c in enumerate((c1, c2)):
            SalesInvoice.objects.create(code=f"t-zi{i}", number=str(i), customer=c,
                                        issued_at=date.today(), amount_rial=10 * (i + 1), channel="team")
        f = rpt.Filters.from_query({"date_from": "2000-01-01"})
        zones = {r["code"]: r for r in rpt.geo_zones(f)["rows"]}
        self.assertEqual(zones["thr-bazar"]["amount"], 10)
        self.assertEqual(zones["thr-other"]["amount"], 20)
        self.assertEqual(rpt.geo_zones(f)["unzoned_customers"], 1)
        other = SalesZone.objects.get(code="thr-other")
        drill = rpt.Filters.from_query({"date_from": "2000-01-01", "zone": other.pk})
        self.assertEqual(list(drill.invoices().values_list("customer_id", flat=True)), [c2.pk])

    def test_zone_must_belong_to_the_customers_province(self):
        SalesZone.ensure_tehran()
        bazar = SalesZone.objects.get(code="thr-bazar")
        c = _customer("t-zz", province=self.fars)
        res = self.client.patch(f"/api/crm/customers/{c.pk}/", {"zone": bazar.pk}, format="json")
        self.assertEqual(res.status_code, 400)


class ColorScaleTests(APITestCase):
    def test_one_huge_province_does_not_wash_out_the_rest(self):
        values = [370, 40, 35, 30, 25, 20, 15, 10, 0, 0]
        breaks = rpt.color_breaks(values, "amount")
        # A province at 35 sits in an upper class, not the bottom one.
        self.assertGreater(sum(1 for b in breaks if 35 >= b), 2)
        self.assertLess(max(breaks), 370)

    def test_achievement_uses_fixed_bins_and_no_data_is_empty(self):
        self.assertEqual(rpt.color_breaks([999], "achievement"), [50, 80, 100, 120])
        self.assertEqual(rpt.color_breaks([0, 0], "amount"), [])
