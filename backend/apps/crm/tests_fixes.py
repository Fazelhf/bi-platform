"""«بدون استان», one group per name, group counts as the list sees them, and
phones from آرپا's party list."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm.models import Customer, CustomerExternalRef, CustomerGroup
from apps.sales.models import DimProvince


def _user(username, role="executive", department=""):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


def _customer(code, **kw):
    return Customer.objects.create(code=code, name_fa=code, first_contact_at=timezone.now(), **kw)


class ProvinceNoneTests(APITestCase):
    def test_customers_without_a_province(self):
        fars = DimProvince.objects.create(code="p-f", name_fa="فارس")
        _customer("pn-1", province=fars)
        _customer("pn-2")
        self.client.force_authenticate(_user("pn-ceo"))
        codes = lambda q: {r["code"] for r in self.client.get("/api/crm/customers/", q).data["results"]}
        self.assertEqual(codes({"province": "none"}), {"pn-2"})
        self.assertEqual(codes({"province": fars.pk}), {"pn-1"})


class GroupTests(APITestCase):
    def setUp(self):
        self.g = CustomerGroup.objects.create(code="g-1", name_fa="نمابر مهر همکار")

    def test_a_second_group_of_the_same_name_is_refused(self):
        self.client.force_authenticate(_user("g-ceo"))
        res = self.client.post("/api/crm/groups/", {"name_fa": "نمابر  مهر همكار"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.patch(f"/api/crm/groups/{self.g.pk}/", {"name_fa": "نمابر مهر همکار"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_the_count_is_what_the_list_shows(self):
        _customer("gc-1", group=self.g, channel="team")
        _customer("gc-2", group=self.g, channel="b2b")
        self.client.force_authenticate(_user("g-team", "manager", "sales_team"))
        row = next(r for r in self.client.get("/api/crm/groups/").data["results"] if r["id"] == self.g.pk)
        listed = self.client.get("/api/crm/customers/", {"group": self.g.pk}).data["count"]
        self.assertEqual(row["customer_count"], listed)

    def test_the_arpa_import_reuses_a_group_of_the_same_name(self):
        from apps.crm.party_sync import PartyWriter

        self.assertEqual(PartyWriter().group("نمابر مهر همكار"), self.g)
        self.assertEqual(CustomerGroup.objects.count(), 1)


class PhoneFillTests(APITestCase):
    def test_fills_only_blanks_on_linked_customers(self):
        from apps.crm.phone_fill import fill

        blank = _customer("ph-1")
        has = _customer("ph-2", phone="02144556677")
        survivor = _customer("ph-3")
        gone = _customer("ph-4", merged_into=survivor)
        for c, code in ((blank, "101"), (has, "102"), (gone, "104")):
            CustomerExternalRef.objects.create(customer=c, source="arpa", external_id=code)
        rows = [
            {"__code": "101", "شماره تلفن": "021-88776655", "موبایل": "09121234567"},
            {"__code": "102", "شماره تلفن": "02100000000"},
            {"__code": "104", "تلفن": "09350000000"},
            {"__code": "999", "تلفن": "02111111111"},
        ]
        report = fill(rows, dry_run=True)
        blank.refresh_from_db()
        self.assertEqual((report.phones, report.mobiles, blank.phone), (1, 2, ""))
        fill(rows)
        blank.refresh_from_db(); has.refresh_from_db(); survivor.refresh_from_db()
        self.assertEqual((blank.phone, blank.mobile), ("021-88776655", "09121234567"))
        self.assertEqual(has.phone, "02144556677")
        self.assertEqual(survivor.mobile, "09350000000")
        self.assertEqual(Customer.objects.count(), 4)
