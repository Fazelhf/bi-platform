"""Customer groups, bulk edit, page size and the scoping of list-wide actions."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm.models import Customer, CustomerGroup
from apps.sales.models import DimEmployee, DimProvince


def _user(username, role="manager", department="sales_team"):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


def _customer(code, name="م", **kw):
    return Customer.objects.create(code=code, name_fa=name, first_contact_at=timezone.now(), **kw)


class GroupTests(APITestCase):
    def setUp(self):
        self.boss = _user("g-boss")
        self.a = CustomerGroup.objects.create(code="g-a", name_fa="الف")
        self.b = CustomerGroup.objects.create(code="g-b", name_fa="ب")
        self.c1 = _customer("g-c1", group=self.a)
        self.c2 = _customer("g-c2", group=self.a)
        self.client.force_authenticate(self.boss)

    def test_create_rename_and_count(self):
        res = self.client.post("/api/crm/groups/", {"name_fa": "عمده‌فروش"}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["code"].startswith("cg-"))
        self.client.patch(f"/api/crm/groups/{res.data['id']}/", {"name_fa": "عمده"}, format="json")
        self.assertEqual(CustomerGroup.objects.get(pk=res.data["id"]).name_fa, "عمده")
        rows = {g["id"]: g for g in self.client.get("/api/crm/groups/").data["results"]}
        self.assertEqual(rows[self.a.pk]["customer_count"], 2)

    def test_move_all_customers_to_another_group(self):
        res = self.client.post(f"/api/crm/groups/{self.a.pk}/move/", {"move_to": self.b.pk}, format="json")
        self.assertEqual(res.data["moved"], 2)
        self.assertEqual(self.b.customers.count(), 2)

    def test_delete_needs_a_destination_and_then_moves(self):
        res = self.client.delete(f"/api/crm/groups/{self.a.pk}/")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["customers"], 2)
        res = self.client.delete(f"/api/crm/groups/{self.a.pk}/?move_to={self.b.pk}")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertFalse(CustomerGroup.objects.filter(pk=self.a.pk).exists())
        self.assertEqual(self.b.customers.count(), 2)

    def test_system_group_cannot_be_deleted(self):
        CustomerGroup.objects.filter(pk=self.b.pk).update(is_system=True)
        self.assertEqual(self.client.delete(f"/api/crm/groups/{self.b.pk}/").status_code, 409)

    def test_another_departments_customers_block_the_delete(self):
        _customer("g-c3", group=self.a, channel="organizational")
        res = self.client.delete(f"/api/crm/groups/{self.a.pk}/?move_to={self.b.pk}")
        self.assertEqual(res.status_code, 409)
        self.assertTrue(CustomerGroup.objects.filter(pk=self.a.pk).exists())
        self.assertEqual(self.a.customers.count(), 3)  # rolled back, nothing moved

    def test_only_managers_write(self):
        self.client.force_authenticate(_user("g-op", "operator"))
        self.assertEqual(self.client.post("/api/crm/groups/", {"name_fa": "x"}, format="json").status_code, 403)


class BulkEditTests(APITestCase):
    def setUp(self):
        self.boss = _user("b-boss")
        self.prov = DimProvince.objects.create(code="b-fars", name_fa="فارس")
        self.grp = CustomerGroup.objects.create(code="b-g", name_fa="گ")
        self.rows = [_customer(f"b-{i}") for i in range(3)]

    def test_one_request_sets_group_and_province(self):
        self.client.force_authenticate(self.boss)
        res = self.client.post("/api/crm/customers/bulk-update/", {
            "ids": [r.pk for r in self.rows], "fields": {"group": self.grp.pk, "province": self.prov.pk},
        }, format="json")
        self.assertEqual(res.data["updated"], 3)
        self.assertEqual(Customer.objects.filter(group=self.grp, province=self.prov).count(), 3)

    def test_per_customer_fields_and_bad_values_are_refused(self):
        self.client.force_authenticate(self.boss)
        url = "/api/crm/customers/bulk-update/"
        ids = [self.rows[0].pk]
        self.assertEqual(self.client.post(url, {"ids": ids, "fields": {"name_fa": "x"}}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"ids": ids, "fields": {"status": "nope"}}, format="json").status_code, 400)

    def test_an_expert_edits_only_their_own_rows_and_never_the_owner(self):
        rep = _user("b-rep", "operator")
        mine = DimEmployee.objects.create(code="b-e", full_name_fa="کارشناس", user=rep)
        Customer.objects.filter(pk=self.rows[0].pk).update(owner=mine)
        self.client.force_authenticate(rep)
        res = self.client.post("/api/crm/customers/bulk-update/", {
            "ids": [r.pk for r in self.rows], "fields": {"province": self.prov.pk},
        }, format="json")
        self.assertEqual(res.data["updated"], 1)
        res = self.client.post("/api/crm/customers/bulk-update/", {
            "ids": [self.rows[0].pk], "fields": {"owner": mine.pk},
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_an_expert_cannot_move_a_customer_to_another_book(self):
        rep = _user("b-rep2", "operator")
        mine = DimEmployee.objects.create(code="b-e2", full_name_fa="کارشناس ۲", user=rep)
        Customer.objects.filter(pk=self.rows[0].pk).update(owner=mine)
        self.client.force_authenticate(rep)
        self.client.patch(f"/api/crm/customers/{self.rows[0].pk}/", {"channel": "b2b", "city": "شیراز"}, format="json")
        self.rows[0].refresh_from_db()
        self.assertEqual((self.rows[0].channel, self.rows[0].city), ("team", "شیراز"))

    def test_bulk_delete_is_scoped(self):
        rep = _user("b-rep3", "operator")
        DimEmployee.objects.create(code="b-e3", full_name_fa="کارشناس ۳", user=rep)
        self.client.force_authenticate(rep)
        res = self.client.post("/api/crm/customers/bulk-delete/", {"ids": [self.rows[1].pk]}, format="json")
        self.assertEqual(res.data["deleted"], 0)
        self.assertTrue(Customer.objects.filter(pk=self.rows[1].pk).exists())

    def test_page_size_500(self):
        Customer.objects.bulk_create([
            Customer(code=f"p-{i}", name_fa=f"م{i}", first_contact_at=timezone.now()) for i in range(520)
        ])
        self.client.force_authenticate(self.boss)
        res = self.client.get("/api/crm/customers/", {"page_size": 500})
        self.assertEqual(len(res.data["results"]), 500)
        self.assertEqual(res.data["count"], 523)
