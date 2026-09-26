"""
منابع انسانی tests.

What has to hold:

* **Only management sees it.** A department manager reads their own team
  through the roster; they do not open the chart.
* **The chart drives the rosters.** Someone placed in فروش همکار is on that
  entry sheet; someone who is not, or who was archived, is off it — without a
  single past figure being deleted.
* **One person, one row.** Spelling variants are recognised, and a duplicate
  can be folded into the original with its history.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod
from apps.hr.models import OrgUnit, Position
from apps.hr.services.names import normalize
from apps.sales.models import DimEmployee, EmployeeChannel, FactSalesMonthly, SalesChannel


def _roster(channel):
    return set(
        EmployeeChannel.objects.filter(channel=channel, is_active=True)
        .values_list("employee__full_name_fa", flat=True)
    )


class HrTestCase(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ceo = User.objects.create_user(username="ceo", password="x", role="executive")
        self.manager = User.objects.create_user(
            username="team-mgr", password="x", role="manager", department="sales_team"
        )
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=3)

    def person(self, name, code=None):
        return DimEmployee.objects.create(code=code or f"t-{DimEmployee.objects.count()}", full_name_fa=name)


class AccessTests(HrTestCase):
    def test_only_management_opens_hr(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get("/api/hr/chart/").status_code, 403)
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.get("/api/hr/chart/").status_code, 200)


class NameTests(HrTestCase):
    def test_spelling_variants_are_the_same_name(self):
        self.assertEqual(normalize("شیما نظام آبادی"), normalize("شيما نظام ابادی"))
        self.assertEqual(normalize("مصطفی میری‌زاده"), normalize("مصطفی میری زاده"))

    def test_creating_a_duplicate_is_refused(self):
        self.person("شیما نظام آبادی")
        self.client.force_authenticate(self.ceo)
        res = self.client.post("/api/hr/people/", {"full_name_fa": "شیما نظام ابادی"}, format="json")
        self.assertEqual(res.status_code, 409)
        forced = self.client.post(
            "/api/hr/people/", {"full_name_fa": "شیما نظام ابادی", "force": True}, format="json"
        )
        self.assertEqual(forced.status_code, 201)


class ChartImportTests(HrTestCase):
    def test_import_places_people_and_rebuilds_rosters(self):
        saba = self.person("صبا موسوی")
        FactSalesMonthly.objects.create(
            period=self.period, employee=saba, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(100),
        )
        gone = self.person("هستی خانی")
        EmployeeChannel.objects.create(employee=gone, channel=SalesChannel.TEAM)

        self.client.force_authenticate(self.ceo)
        res = self.client.post("/api/hr/chart/import/")
        self.assertEqual(res.status_code, 201, res.data)

        team = _roster(SalesChannel.TEAM)
        self.assertIn("صبا موسوی", team)
        # Not on the chart: off the sheet, but still a person with history.
        self.assertNotIn("هستی خانی", team)
        self.assertTrue(DimEmployee.objects.filter(pk=gone.pk).exists())
        # A سرپرست supervises; the seat does not put him on the sheet.
        self.assertNotIn("محمد محسن شاهان", team)
        # The existing row was reused rather than a second صبا created.
        self.assertEqual(DimEmployee.objects.filter(full_name_fa="صبا موسوی").count(), 1)
        self.assertEqual(FactSalesMonthly.objects.filter(employee=saba).count(), 1)

        self.assertIn("نازنین کمیجانی", _roster(SalesChannel.ORGANIZATIONAL))
        self.assertIn("هانیه منزه", _roster(SalesChannel.PSP))
        self.assertEqual(_roster(SalesChannel.B2B), {"سارا مسگرچیان"})

        self.assertEqual(self.client.post("/api/hr/chart/import/").status_code, 400)


class ChartEditTests(HrTestCase):
    def setUp(self):
        super().setUp()
        self.sales = OrgUnit.objects.create(name_fa="فروش", kind="department")
        self.team = OrgUnit.objects.create(
            name_fa="فروش همکار", parent=self.sales, sales_channel=SalesChannel.TEAM
        )
        self.rep = self.person("پارسا مروتی")
        self.client.force_authenticate(self.ceo)

    def test_placing_someone_puts_them_on_the_sheet(self):
        res = self.client.post("/api/hr/positions/", {
            "unit": self.team.id, "title_fa": "کارشناس فروش", "holder": self.rep.id,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(_roster(SalesChannel.TEAM), {"پارسا مروتی"})

        # Moving the seat to vacant takes them off again.
        self.client.patch(f"/api/hr/positions/{res.data['id']}/", {"holder": None}, format="json")
        self.assertEqual(_roster(SalesChannel.TEAM), set())

    def test_archiving_empties_the_seat_and_keeps_the_history(self):
        seat = Position.objects.create(unit=self.team, title_fa="کارشناس", holder=self.rep)
        FactSalesMonthly.objects.create(
            period=self.period, employee=self.rep, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(5),
        )
        res = self.client.post(f"/api/hr/people/{self.rep.id}/archive/", {"note": "خروج"}, format="json")
        self.assertEqual(res.status_code, 200)

        seat.refresh_from_db()
        self.rep.refresh_from_db()
        self.assertIsNone(seat.holder)
        self.assertFalse(self.rep.is_active)
        self.assertEqual(_roster(SalesChannel.TEAM), set())
        self.assertEqual(FactSalesMonthly.objects.filter(employee=self.rep).count(), 1)

        # And an archived person cannot be put back in a seat until restored.
        res = self.client.patch(f"/api/hr/positions/{seat.id}/", {"holder": self.rep.id}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_unclaimed_channels_are_left_alone(self):
        other = self.person("مهسا احمدی")
        EmployeeChannel.objects.create(employee=other, channel=SalesChannel.ORGANIZATIONAL)
        Position.objects.create(unit=self.team, title_fa="کارشناس", holder=self.rep)
        self.client.post("/api/hr/sync-rosters/")
        self.assertEqual(_roster(SalesChannel.ORGANIZATIONAL), {"مهسا احمدی"})

    def test_a_unit_cannot_move_under_itself(self):
        res = self.client.patch(f"/api/hr/units/{self.sales.id}/", {"parent": self.team.id}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_department_manager_can_no_longer_edit_a_claimed_roster(self):
        self.client.force_authenticate(self.manager)
        res = self.client.post("/api/sales/roster/", {"name": "نام تازه"}, format="json")
        self.assertEqual(res.status_code, 403)

        res = self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "team",
            "columns": [{"name": "کسی که در چارت نیست"}],
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(DimEmployee.objects.filter(full_name_fa="کسی که در چارت نیست").exists())


class MergeTests(HrTestCase):
    def test_merge_moves_history_and_removes_the_duplicate(self):
        real = self.person("شیما نظام آبادی")
        dup = self.person("شیما نظام ابادی")
        FactSalesMonthly.objects.create(
            period=self.period, employee=dup, channel=SalesChannel.B2B, revenue_rial=Decimal(9),
        )
        EmployeeChannel.objects.create(employee=dup, channel=SalesChannel.B2B)

        self.client.force_authenticate(self.ceo)
        dupes = self.client.get("/api/hr/people/duplicates/").data
        self.assertEqual(len(dupes), 1)

        res = self.client.post(f"/api/hr/people/{dup.id}/merge/", {"into": real.id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(DimEmployee.objects.filter(pk=dup.pk).exists())
        self.assertEqual(FactSalesMonthly.objects.get().employee_id, real.id)
        self.assertTrue(EmployeeChannel.objects.filter(employee=real, channel="b2b").exists())

    def test_merge_refuses_when_both_have_the_same_month(self):
        real = self.person("الف")
        dup = self.person("ب")
        for e in (real, dup):
            FactSalesMonthly.objects.create(
                period=self.period, employee=e, channel=SalesChannel.TEAM, revenue_rial=Decimal(1),
            )
        self.client.force_authenticate(self.ceo)
        res = self.client.post(f"/api/hr/people/{dup.id}/merge/", {"into": real.id}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(DimEmployee.objects.filter(pk=dup.pk).exists())


class AccountTests(HrTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            username="root", password="x", email="r@example.com"
        )
        self.rep = self.person("نازنین کمیجانی")

    def test_admin_creates_and_links_an_account(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(f"/api/hr/people/{self.rep.id}/account/", {
            "username": "n.kamijani", "password": "Str0ng!Passw0rd#2026",
            "department": "sales_org",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.user.username, "n.kamijani")
        self.assertEqual(self.rep.user.display_name_fa, "نازنین کمیجانی")
        self.assertTrue(self.rep.user.check_password("Str0ng!Passw0rd#2026"))
        self.assertEqual(res.data["user"], self.rep.user_id)

        # A second account for the same person is refused.
        again = self.client.post(f"/api/hr/people/{self.rep.id}/account/", {
            "username": "other", "password": "Str0ng!Passw0rd#2026",
        }, format="json")
        self.assertEqual(again.status_code, 400)

    def test_ceo_sees_accounts_but_cannot_create_them(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.post(f"/api/hr/people/{self.rep.id}/account/", {
            "username": "x.y", "password": "Str0ng!Passw0rd#2026",
        }, format="json")
        self.assertEqual(res.status_code, 403)
        self.rep.refresh_from_db()
        self.assertIsNone(self.rep.user_id)


class HardDeleteTests(HrTestCase):
    def setUp(self):
        super().setUp()
        self.root = get_user_model().objects.create_superuser(
            username="root2", password="x", email="r2@example.com"
        )
        self.junk = self.person("رکورد اشتباه")
        FactSalesMonthly.objects.create(
            period=self.period, employee=self.junk, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(7),
        )
        EmployeeChannel.objects.create(employee=self.junk, channel=SalesChannel.TEAM)

    def test_only_the_main_admin_may_delete(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.delete(f"/api/hr/people/{self.junk.id}/", {"confirm": "رکورد اشتباه"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.get(f"/api/hr/people/{self.junk.id}/delete-preview/").status_code, 403)
        self.assertTrue(DimEmployee.objects.filter(pk=self.junk.pk).exists())

    def test_wrong_confirmation_deletes_nothing(self):
        self.client.force_authenticate(self.root)
        res = self.client.delete(f"/api/hr/people/{self.junk.id}/", {"confirm": "اشتباه"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(DimEmployee.objects.filter(pk=self.junk.pk).exists())

    def test_deletes_the_person_with_their_data(self):
        self.client.force_authenticate(self.root)
        preview = self.client.get(f"/api/hr/people/{self.junk.id}/delete-preview/")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("sales.FactSalesMonthly", [r["model"] for r in preview.data["deleted"]])

        res = self.client.delete(f"/api/hr/people/{self.junk.id}/", {"confirm": "رکورد اشتباه"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(DimEmployee.objects.filter(pk=self.junk.pk).exists())
        self.assertEqual(FactSalesMonthly.objects.count(), 0)
        self.assertEqual(EmployeeChannel.objects.count(), 0)


class LinkAccountTests(HrTestCase):
    """Someone who already signs in keeps that one login when they join the chart."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="root3", password="x", email="r3@example.com"
        )
        self.rep = self.person("سارا موسوی")
        self.existing = User.objects.create_user(username="s.mousavi", password="x", role="operator")

    def link(self, person, user):
        return self.client.post(
            f"/api/hr/people/{person.id}/link-account/", {"user": user.id}, format="json"
        )

    def test_admin_links_an_existing_account(self):
        self.client.force_authenticate(self.admin)
        res = self.link(self.rep, self.existing)
        self.assertEqual(res.status_code, 200, res.data)
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.user_id, self.existing.id)
        self.assertEqual(res.data["username"], "s.mousavi")

    def test_an_account_linked_to_someone_else_is_refused(self):
        other = self.person("فرد دیگر")
        other.user = self.existing
        other.save(update_fields=["user"])
        self.client.force_authenticate(self.admin)
        res = self.link(self.rep, self.existing)
        self.assertEqual(res.status_code, 400)
        self.rep.refresh_from_db()
        self.assertIsNone(self.rep.user_id)

    def test_a_person_who_has_an_account_cannot_take_another(self):
        self.rep.user = get_user_model().objects.create_user(username="own", password="x")
        self.rep.save(update_fields=["user"])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.link(self.rep, self.existing).status_code, 400)

    def test_ceo_cannot_link_accounts(self):
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.link(self.rep, self.existing).status_code, 403)
