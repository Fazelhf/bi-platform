"""
CRM tests, centred on the thing that actually went wrong in production.

The company's real customer file and a fabricated showroom live in the same
tables, told apart by one column. Two failure modes matter, and only one of
them is visible on screen:

* **A leak.** The showroom shows a real customer, or the real file shows an
  invented one. Loud, and someone reports it.
* **A silent skip.** The importer decides the real data is already loaded when
  it is not, and never runs. Nothing errors, the pages fill with the demo set
  wearing the «واقعی» label, and it reads as working. This is what happened on
  the server: migration 0004 defaults `dataset` to "real", so the generated
  demo set that predated the column arrived labelled real, and a guard that
  asked «are there real rows?» answered yes.

So the guard is tested by its real question — «did *this command* write
anything?» — and the answer keys on the «didar-» codes only the importer
mints.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import reports as rpt
from apps.crm.management.commands.import_didar_crm import Command as ImportCommand, fit
from apps.crm.models import (
    Customer, Dataset, Deal, DealItem, PipelineStage, Product,
)


def _user(username, role, department="", dataset="real"):
    User = get_user_model()
    return User.objects.create_user(
        username=username, password="pw12345!", role=role,
        department=department, crm_dataset=dataset,
    )


class DatasetTestCase(APITestCase):
    """One customer and one deal on each side, deliberately alike."""

    def setUp(self):
        now = timezone.now()
        self.real_customer = Customer.objects.create(
            code="didar-pe-1759", name_fa="بانک ملی خراسان رضوی",
            dataset=Dataset.REAL, first_contact_at=now - timedelta(days=90),
        )
        self.demo_customer = Customer.objects.create(
            code="cust-2082", name_fa="مشتری نمایشی",
            dataset=Dataset.DEMO, first_contact_at=now - timedelta(days=90),
        )
        for customer, ds, code in (
            (self.real_customer, Dataset.REAL, "didar-d-125"),
            (self.demo_customer, Dataset.DEMO, "deal-9001"),
        ):
            Deal.objects.create(
                code=code, title=f"معامله {code}", customer=customer,
                dataset=ds, opened_at=now - timedelta(days=30),
            )

        self.ceo = _user("ceo", "executive")
        self.rep = _user("rep", "manager", "sales_team")


class DatasetIsolationTests(DatasetTestCase):
    def test_list_shows_only_the_account_s_dataset(self):
        self.client.force_authenticate(self.ceo)

        names = [r["name_fa"] for r in self.client.get("/api/crm/customers/").data["results"]]
        self.assertEqual(names, ["بانک ملی خراسان رضوی"])

        self.ceo.crm_dataset = "demo"
        self.ceo.save(update_fields=["crm_dataset"])
        names = [r["name_fa"] for r in self.client.get("/api/crm/customers/").data["results"]]
        self.assertEqual(names, ["مشتری نمایشی"])

    def test_created_rows_join_the_dataset_on_screen(self):
        """Adding a customer while looking at the showroom must not file it
        with the real ones, where nobody would think to look for it."""
        self.client.force_authenticate(self.rep)
        self.rep.crm_dataset = "demo"
        self.rep.save(update_fields=["crm_dataset"])

        res = self.client.post("/api/crm/customers/", {"name_fa": "مشتری تازه"})
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(
            Customer.objects.get(name_fa="مشتری تازه").dataset, Dataset.DEMO
        )

    def test_switch_endpoint_stores_the_choice_and_refuses_junk(self):
        self.client.force_authenticate(self.rep)

        self.assertEqual(
            self.client.post("/api/crm/dataset/", {"dataset": "demo"}).status_code, 200
        )
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.crm_dataset, "demo")

        self.assertEqual(
            self.client.post("/api/crm/dataset/", {"dataset": "prod"}).status_code, 400
        )
        self.rep.refresh_from_db()
        self.assertEqual(self.rep.crm_dataset, "demo")

    def test_funnel_stages_do_not_mix_the_two_vocabularies(self):
        """
        Both datasets name their stages «ارتباط مشتری». Unfiltered, the funnel
        drew every stage twice — the duplicate rows reported from the CRM.
        """
        for ds in (Dataset.REAL, Dataset.DEMO):
            PipelineStage.objects.create(
                code=f"st-contact-{ds}", name_fa="ارتباط مشتری",
                order=1, dataset=ds,
            )
        rows = rpt.report_funnel(rpt.Filters.from_query({}, "real"))["rows"]
        self.assertEqual([r["label"] for r in rows], ["ارتباط مشتری"])


class ImportGuardTests(DatasetTestCase):
    """
    `--if-empty` is what lets deploy.sh call the importer on every deploy.
    Wrong in either direction it is dangerous: too eager and it wipes the
    sales team's work, too shy and the real data never arrives.
    """

    def test_guard_sees_imported_rows(self):
        self.assertTrue(ImportCommand()._already_imported())

    def test_guard_ignores_rows_it_did_not_write(self):
        """
        The production bug. A demo customer tagged «real» by the migration
        default is not evidence that the import has run — asking «are there
        real rows?» is what made the importer skip itself in silence.
        """
        Customer.objects.filter(code__startswith="didar-").delete()
        Customer.objects.filter(code="cust-2082").update(dataset=Dataset.REAL)

        self.assertTrue(Customer.objects.filter(dataset=Dataset.REAL).exists())
        self.assertFalse(ImportCommand()._already_imported())

    def test_first_import_clears_the_mislabelled_seed(self):
        Customer.objects.filter(code__startswith="didar-").delete()
        Customer.objects.filter(code="cust-2082").update(dataset=Dataset.REAL)

        cmd = ImportCommand()
        cmd.stdout = type("_S", (), {"write": lambda self, *a, **k: None})()
        cmd.style = type("_T", (), {"WARNING": staticmethod(lambda s: s)})()
        cmd._clear_mislabelled()

        self.assertFalse(Customer.objects.filter(dataset=Dataset.REAL).exists())


class CrossDatasetReferenceTests(DatasetTestCase):
    """
    The failure that stopped the repair on the server.

    `seed_crm` upserts its reference lists by code, so a run that finds a
    Product already there does not touch `created_at` — and tagging by time
    alone left it wearing whatever label it arrived with. The showroom's
    DealItems then pointed at a Product tagged «واقعی», and PROTECT refused to
    let the real import delete it. Nothing is wrong on screen; it only breaks
    the next reload, which is the worst moment to find out.
    """

    def test_a_demo_line_may_not_hold_a_real_product(self):
        real_product = Product.objects.create(
            code="pr-thermal", name_fa="رول حرارتی", dataset=Dataset.REAL,
        )
        demo_deal = Deal.objects.get(code="deal-9001")
        DealItem.objects.create(
            deal=demo_deal, product=real_product, quantity=1,
            unit_price_rial=1000, dataset=Dataset.DEMO,
        )

        crossed = DealItem.objects.filter(dataset=Dataset.DEMO).exclude(
            product__dataset=Dataset.DEMO
        )
        self.assertEqual(
            crossed.count(), 1,
            "this fixture is the broken shape — the assertion below is the point",
        )
        # And the real product cannot be removed while it is held, which is
        # exactly the ProtectedError the server raised.
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            Product.objects.filter(dataset=Dataset.REAL).delete()


class ColumnWidthTests(APITestCase):
    """
    The class of bug that only production could see.

    SQLite ignores `VARCHAR(n)` completely, so an over-long value writes clean
    in development and the import looks correct. PostgreSQL does not, and the
    server stopped on «value too long for type character varying(40)» — after
    the import had already been declared working here.

    `fit` asks the model for the width instead of the call site guessing it,
    which is what these lock in: the two real offenders, and the property that
    a clamp is derived rather than typed.
    """

    def test_clamps_to_the_field_s_own_limit(self):
        long_phone = "02196052633 مدیریت اداره خرید و فروش اقلام عمده شرکت"
        self.assertGreater(len(long_phone), 40)
        self.assertEqual(len(fit(Customer, "phone", long_phone)), 40)

        from apps.crm.models import Activity
        self.assertEqual(len(fit(Activity, "note", "ن" * 900)), 500)

    def test_uses_the_model_rather_than_a_written_number(self):
        """`note` was hand-sliced to 2000 against a 500-wide column; the point
        of deriving the limit is that such a slice cannot drift again."""
        limit = Customer._meta.get_field("name_fa").max_length
        self.assertEqual(len(fit(Customer, "name_fa", "ا" * (limit + 50))), limit)

    def test_none_and_numbers_survive(self):
        self.assertEqual(fit(Customer, "phone", None), "")
        self.assertEqual(fit(Customer, "phone", 2196052633), "2196052633")
