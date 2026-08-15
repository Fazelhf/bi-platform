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
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import matching, merge as crm_merge, reports as rpt
from apps.crm.management.commands.import_arpa_invoices import (
    Command as InvoiceCommand, dec as inv_dec,
)
from apps.crm.matching import CustomerIndex, Method
from apps.crm.management.commands.import_didar_crm import Command as ImportCommand, fit
from apps.crm.models import (
    Customer, CustomerExternalRef, CustomerMatchCandidate, Dataset, Deal, DealItem, ExternalSource,
    PipelineStage, Product, SalesInvoice, SalesInvoiceItem,
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


class IdentityLayerTests(DatasetTestCase):
    """
    A customer has to be reachable by *each* source system's own id.

    Until accounting arrived there was one source, and `Customer.code` could
    carry both the row's name and its origin («didar-co-46206»). A second
    source breaks that: آرپا's کد طرف حساب has nowhere to live, so the same
    company is imported again under a new code and every per-customer figure
    silently splits in two.
    """

    def test_the_importer_files_the_didar_id_where_a_second_source_can_look(self):
        """
        The id has to end up somewhere queryable — not only inside `code`.
        Derived from `code` so it matches, row for row, what migration 0006
        backfilled onto the customers already in the production database.
        """
        ImportCommand._link(self.real_customer)

        ref = self.real_customer.external_refs.get(source=ExternalSource.DIDAR)
        self.assertEqual(ref.external_id, "pe-1759")
        self.assertEqual(ref.external_name, self.real_customer.name_fa)

    def test_link_is_idempotent_and_survives_a_rename(self):
        """
        The importer runs again whenever a fresher export arrives. A second
        run must update the row it already wrote, not add a second id — and a
        company renamed in دیدار must keep its id rather than fork.
        """
        ImportCommand._link(self.real_customer)
        self.real_customer.name_fa = "نام تازه"
        self.real_customer.save(update_fields=["name_fa", "updated_at"])
        ImportCommand._link(self.real_customer)

        self.assertEqual(self.real_customer.external_refs.count(), 1)
        ref = self.real_customer.external_refs.get(source=ExternalSource.DIDAR)
        self.assertEqual(ref.external_name, "نام تازه")

    def test_one_source_id_cannot_name_two_customers(self):
        """
        The constraint that makes a merge decision final. Without it a later
        import pass could quietly attach آرپا's کد ۴۰۰۷۲۱ to a different
        customer than the reviewer chose, and nothing would complain.
        """
        other = Customer.objects.create(
            code="didar-co-duplicate", name_fa="شرکت دوم",
            first_contact_at=timezone.now(),
        )
        CustomerExternalRef.objects.create(
            source=ExternalSource.ARPA, external_id="400721",
            customer=self.real_customer,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerExternalRef.objects.create(
                source=ExternalSource.ARPA, external_id="400721", customer=other,
            )

    def test_the_same_id_may_repeat_across_sources(self):
        """دیدار and آرپا number their parties independently; «۱۰۰» in one is
        unrelated to «۱۰۰» in the other, so the key is the pair."""
        CustomerExternalRef.objects.create(
            source=ExternalSource.ARPA, external_id="100",
            customer=self.real_customer,
        )
        CustomerExternalRef.objects.create(
            source=ExternalSource.DIDAR, external_id="100",
            customer=self.real_customer,
        )
        self.assertEqual(
            self.real_customer.external_refs.filter(external_id="100").count(), 2
        )


class InvoiceSeparationTests(DatasetTestCase):
    """
    Invoice money and deal money must not be the same number.

    `Deal.amount_rial` comes from دیدار and دیدار's own reports are built on
    it — the importer checks itself against those totals. An invoice is what
    accounting actually billed. Keeping them apart is what lets «چقدر از کاریز
    فاکتور شد» be a question with an answer instead of a tautology.
    """

    def setUp(self):
        super().setUp()
        self.customer = self.real_customer

    def _invoice(self, number, kind, amount):
        return SalesInvoice.objects.create(
            code=f"arpa-inv-{number}", number=number, kind=kind,
            customer=self.customer, issued_at=timezone.now().date(),
            amount_rial=amount,
        )

    def test_invoicing_a_customer_leaves_the_deal_untouched(self):
        deal = Deal.objects.filter(customer=self.customer).first()
        if deal is None:
            self.skipTest("fixture has no deal for this customer")
        before = deal.amount_rial

        self._invoice("1001", SalesInvoice.Kind.SALE, 5_000_000)

        deal.refresh_from_db()
        self.assertEqual(deal.amount_rial, before)

    def test_a_return_sums_against_the_sale_it_reverses(self):
        """
        آرپا writes مرجوعی with a negative مبلغ فروش. Storing the sign as
        given means a plain SUM over a period is already net of returns —
        the alternative is every report remembering to subtract, and one of
        them eventually not doing it.
        """
        self._invoice("1002", SalesInvoice.Kind.SALE, 10_000_000)
        self._invoice("1003", SalesInvoice.Kind.RETURN, -4_000_000)

        total = SalesInvoice.objects.filter(customer=self.customer).aggregate(
            t=Sum("amount_rial")
        )["t"]
        self.assertEqual(total, 6_000_000)

    def test_a_line_survives_a_product_the_catalogue_does_not_have(self):
        """
        The آرپا catalogue and the دیدار one only partly line up. A sale of an
        unmappable product is still revenue, so the line keeps the source's
        own code and name and refuses to be dropped.
        """
        invoice = self._invoice("1004", SalesInvoice.Kind.SALE, 3_000_000)
        item = SalesInvoiceItem.objects.create(
            invoice=invoice, product=None,
            product_code="51300", product_name="49 - 16 - ساده",
            quantity=7200, unit_price_rial=115_500, amount_rial=831_600_000,
        )
        self.assertIsNone(item.product)
        self.assertEqual(invoice.items.count(), 1)


class NormalisationTests(APITestCase):
    """
    The folding is what makes the exact-name tier work at all.

    آرپا writes legacy Persian — Arabic ي (U+064A) and ك (U+0643) — and دیدار
    writes ی and ک. Compared as typed, the same company name from the two
    systems is two different strings, and every tier below «exact name» would
    have to carry the whole customer file.
    """

    def test_the_two_systems_spell_the_same_name_identically_once_folded(self):
        arpa = "شرکت خدمات بهداشتي آواي سلامت پارس"   # ي, ك
        didar = "شرکت خدمات بهداشتی آوای سلامت پارس"   # ی, ک
        self.assertNotEqual(arpa, didar)
        self.assertEqual(matching.name_key(arpa), matching.name_key(didar))

    def test_descriptive_words_do_not_identify_a_company(self):
        self.assertEqual(
            matching.name_key("شرکت بازرگانی ایران ارقام سهامی خاص"),
            matching.name_key("ایران ارقام"),
        )
        self.assertEqual(matching.name_key("آقای انجوی"), matching.name_key("انجوی"))

    def test_zwnj_and_persian_digits_fold(self):
        self.assertEqual(matching.name_key("نمابر\u200cمهر"), "نمابر مهر")
        self.assertEqual(matching.phone_key("۰۲۱۴۴۶۴۱۳۳۰"), "44641330")

    def test_phone_key_sees_through_dialling_prefixes(self):
        for written in ("02144641330", "44641330", "021-4464-1330", "+982144641330"):
            self.assertEqual(matching.phone_key(written), "44641330", written)

    def test_a_short_number_is_not_a_key(self):
        """Four digits shared by hundreds of rows would match everything."""
        self.assertEqual(matching.phone_key("4464"), "")
        self.assertEqual(matching.id_key("123"), "")


class PlaceGuardTests(APITestCase):
    """
    The false positive that set the threshold policy.

    «بانک کشاورزی ایلام» and «بانک کشاورزی گیلان» are 86% alike by character
    overlap — above any fuzzy threshold worth having — and are branches in
    provinces 900km apart. A bank with a branch in every province makes string
    similarity actively dangerous, so a disagreement about *place* vetoes the
    similarity rather than being outweighed by it.
    """

    def test_two_provinces_are_not_one_customer(self):
        self.assertGreater(
            matching.similarity("بانک کشاورزی ایلام", "بانک کشاورزی گیلان"),
            matching.FUZZY_FLOOR,
        )
        self.assertTrue(
            matching.place_conflict("بانک کشاورزی ایلام", "بانک کشاورزی گیلان")
        )

    def test_silence_about_place_is_not_disagreement(self):
        """«بانک سینا» and «بانک سینا تهران» may well be one account."""
        self.assertFalse(matching.place_conflict("بانک سینا", "بانک سینا تهران"))

    def test_the_same_place_written_twice_is_agreement(self):
        self.assertFalse(
            matching.place_conflict("بانک کشاورزی البرز-کرج", "بانک کشاورزی البرز")
        )


class MatchLadderTests(APITestCase):
    """
    Which rung answers decides whether a customer is merged or merely
    suggested. A wrong merge fuses two companies' order history and nothing
    on screen looks wrong afterwards, so only the top rungs may write.
    """

    def setUp(self):
        self.index = CustomerIndex()
        self.index.add(1, name="ایران ارقام", nids=("10100905654",), phones=("02142719000",))
        self.index.add(2, name="بانک کشاورزی ایلام", phones=("08433330000",))
        self.index.add(3, name="پلی کلینیک سوم خرداد", phones=("06153500000",))
        self.index.add(4, name="شبکه بهداشت خرمشهر", phones=("06153500000",))

    def _find(self, **kw):
        kw.setdefault("source", "arpa")
        kw.setdefault("external_id", "9999")
        kw.setdefault("nids", ())
        kw.setdefault("phones", ())
        return self.index.find(**kw)

    def test_a_previous_run_s_link_wins_over_everything(self):
        """Re-running the import must land on the row the reviewer chose, not
        re-derive an answer that may have drifted."""
        self.index.add_ref("arpa", "400721", 2)
        match = self._find(external_id="400721", name="ایران ارقام")
        self.assertEqual(match.customer_id, 2)
        self.assertTrue(match.is_auto)

    def test_the_same_name_spelled_the_other_way_merges_unattended(self):
        match = self._find(name="شرکت ايران ارقام")
        self.assertEqual((match.method, match.customer_id), (Method.NAME, 1))
        self.assertTrue(match.is_auto)

    def test_a_shared_switchboard_is_only_a_suggestion(self):
        """
        The measured failure: a clinic and a health authority in خرمشهر answer
        one number. Phone finds a pair, and the pair must not be written.
        """
        match = self._find(name="درمانگاه تازه", phones=("06153500000",))
        self.assertEqual(match.method, Method.PHONE)
        self.assertTrue(match.found)
        self.assertFalse(match.is_auto)

    def test_a_sister_province_branch_is_not_matched_at_all(self):
        match = self._find(name="بانک کشاورزی گیلان")
        self.assertEqual(match.method, Method.NONE)
        self.assertIsNone(match.customer_id)

    def test_a_name_shared_by_two_customers_is_flagged_not_merged(self):
        """
        A duplicate already inside the CRM. Merging into either half would
        bury it; the reviewer has to settle that first.
        """
        self.index.add(5, name="ایران ارقام")
        match = self._find(name="ایران ارقام")
        self.assertEqual(match.method, Method.AMBIGUOUS)
        self.assertFalse(match.is_auto)

    def test_a_national_id_suggests_but_never_writes(self):
        """
        It names a legal entity, and the customers here are its branches —
        every one of them carrying the head office's number. Trusting it
        merged seventeen پست بانک branches into a single «دولتی پست بانک».
        دیدار carries no national id at all, so the tier could never link the
        two systems anyway: it can only join آرپا parties to each other, which
        is precisely the damage.
        """
        match = self._find(name="نام کاملا متفاوت", nids=("10100905654",))
        self.assertEqual((match.method, match.customer_id), (Method.NATIONAL_ID, 1))
        self.assertFalse(match.is_auto)

    def test_an_unknown_party_is_left_unmatched(self):
        match = self._find(name="شرکت تازه وارد", phones=("02100000000",))
        self.assertEqual(match.method, Method.NONE)


class BranchNationalIdTests(APITestCase):
    """
    The bug a second import run produced, and why the top rung is not enough.

    A شناسه ملی identifies a legal entity. The customers here are largely that
    entity's branches, and every branch of بانک صادرات carries the head
    office's number. Run one created the branches from آرپا with their ids;
    run two matched them to each other by id and merged «بانک صادرات
    کرمانشاه» into «بانک صادرات آذربایجان» — a wrong merge, arriving through
    the rung the ladder trusts most, and invisible on any screen afterwards.

    Two branches may well be one account. That is a decision about how the
    company sells, and an identifier cannot make it.
    """

    def setUp(self):
        self.index = CustomerIndex()
        self.SHARED = "10861904730"
        self.index.add(1, name="بانک صادرات آذربایجان", nids=(self.SHARED,))

    def _find(self, name, nids):
        return self.index.find(
            source="arpa", external_id="1", name=name, nids=nids, phones=(),
        )

    def test_a_second_branch_is_not_merged_into_the_first(self):
        match = self._find("بانک صادرات کرمانشاه", (self.SHARED,))
        self.assertEqual(match.method, Method.BRANCH)
        self.assertFalse(match.is_auto)
        self.assertTrue(match.found, "the pair is still worth showing a reviewer")

    def test_no_id_match_writes_itself_whatever_the_names_say(self):
        """
        The place guard narrowed this and did not close it: a head-office row
        names no place, so it never disagrees, and «پست بانک کرمان» merged
        into «دولتی پست بانک» through a rung that saw no conflict at all.
        """
        for name in ("صادرات آذربایجان", "بانک صادرات", "بانک صادرات کرمانشاه"):
            self.assertFalse(self._find(name, (self.SHARED,)).is_auto, name)

    def test_the_ladder_does_not_reach_the_id_when_a_link_exists(self):
        """A reviewer's decision outranks every heuristic, including this."""
        self.index.add(2, name="بانک صادرات کرمانشاه")
        self.index.add_ref("arpa", "77", 2)
        match = self.index.find(
            source="arpa", external_id="77", name="بانک صادرات کرمانشاه",
            nids=(self.SHARED,), phones=(),
        )
        self.assertEqual((match.method, match.customer_id), (Method.EXISTING, 2))


class InvoiceImportUnitTests(APITestCase):
    """
    The three shapes in the آرپا export that decide whether the totals are
    right, each of which reads as a plausible number when handled wrong.
    """

    def test_the_invoice_key_survives_a_year_rollover(self):
        """
        «شماره برگه» restarts each year and «شماره ثابت سند» is not unique
        either — 868 distinct values for 1,098 rows. Only (kind, number, date)
        is unique on all of them, so the code carries the date.
        """
        from datetime import date
        code_1404 = InvoiceCommand._code("sale", "241", date(2025, 6, 15))
        code_1405 = InvoiceCommand._code("sale", "241", date(2026, 6, 15))
        self.assertNotEqual(code_1404, code_1405)
        self.assertLessEqual(len(code_1404), 50)

    def test_a_totals_row_is_not_an_invoice(self):
        """
        Every file carries one row with no نوع برگه whose amount equals the
        sum of all the others. Counted, it doubles revenue exactly — which
        looks like a very good year rather than like a bug.
        """
        rows = [
            {"نوع برگه": "فاکتور فروش", "مبلغ فروش": 100},
            {"نوع برگه": "فاکتور فروش", "مبلغ فروش": 250},
            {"نوع برگه": None, "مبلغ فروش": 350},
        ]
        real = [r for r in rows if matching.fold(r.get("نوع برگه"))]
        self.assertEqual(len(real), 2)
        self.assertEqual(sum(inv_dec(r["مبلغ فروش"]) for r in real), 350)

    def test_a_return_keeps_the_sign_the_source_gave_it(self):
        self.assertEqual(inv_dec("-1,446,702,200"), Decimal("-1446702200"))
        self.assertEqual(inv_dec("948,000,000"), Decimal("948000000"))
        self.assertEqual(inv_dec(None), Decimal(0))
        self.assertEqual(inv_dec("چیزی نیست"), Decimal(0))


class InvoiceRepMappingTests(APITestCase):
    """
    The same colleague, spelled two ways in two systems. Left unmatched, a
    third of the invoices lose their owner; matched too eagerly, two people
    become one and both their numbers are wrong.
    """

    def setUp(self):
        self.cmd = InvoiceCommand()
        self.cmd.unknown_reps = defaultdict(int)
        self.cmd.employees = {
            matching.name_key(n): n for n in (
                "هانیه منزه", "حامد بهشتی", "بهلول", "مهدیس مومنی",
                "سارا مسگرچیان", "پیام بوساک", "صبا موسوی",
            )
        }

    def test_an_extra_name_part_is_the_same_person(self):
        """«هانیه خواجه منزه» in آرپا is «هانیه منزه» in the CRM."""
        self.assertEqual(self.cmd._rep("هانیه خواجه منزه"), "هانیه منزه")
        self.assertEqual(self.cmd._rep("حامد بهشتی زواره"), "حامد بهشتی")

    def test_a_surname_only_colleague_still_matches(self):
        self.assertEqual(self.cmd._rep("عاطفه بهلول"), "بهلول")

    def test_hamza_is_not_a_different_person(self):
        self.assertEqual(self.cmd._rep("مهدیس موءمنی"), "مهدیس مومنی")

    def test_a_different_surname_is_never_inferred(self):
        """
        A rule loose enough to pair «سارا مسگرقمی» with «سارا مسگرچیان» would
        also fuse two colleagues who merely share a given name, and a fused
        colleague halves a real person's numbers wherever they are reported.
        So the rule refuses, and the invoice is left unowned — visibly.
        """
        self.assertIsNone(self.cmd._rep("سارا مسگری"))
        self.assertIsNone(self.cmd._rep("کاوه بهشتی"))
        self.assertEqual(set(self.cmd.unknown_reps), {"سارا مسگری", "کاوه بهشتی"})

    def test_a_confirmed_pair_is_written_down_not_derived(self):
        """
        «محسن بوساک» is «پیام بوساک» and «سارا مسگرقمی» is «سارا مسگرچیان» —
        confirmed by the sales manager, and underivable, because it is the
        name that differs rather than its spelling. Listing them by hand is
        what keeps the general rule tight.
        """
        self.assertEqual(self.cmd._rep("محسن بوساک"), "پیام بوساک")
        self.assertEqual(self.cmd._rep("سارا مسگرقمی"), "سارا مسگرچیان")
        self.assertFalse(self.cmd.unknown_reps)

    def test_the_placeholder_is_not_a_colleague(self):
        """425 of 1,098 invoices carry «بازاریاب بدون پورسانت»."""
        self.assertIsNone(self.cmd._rep("بازاریاب بدون پورسانت"))
        self.assertNotIn("بازاریاب بدون پورسانت", self.cmd.unknown_reps)


class MergeReviewTests(APITestCase):
    """
    What a reviewer's decision does.

    Both answers must end with the آرپا party carrying an external ref. An
    unresolved party is invisible to the invoice import — 260 invoices worth
    543bn Rial are waiting on this queue — so «reject» meaning «drop it»
    would quietly make that money unimportable for good.
    """

    def setUp(self):
        now = timezone.now()
        self.customer = Customer.objects.create(
            code="didar-co-500", name_fa="بانک سپه سبلان",
            dataset=Dataset.REAL, first_contact_at=now,
        )
        self.payload = {
            "کد": "400721", "نام": "بانک سپه شعبه سبلان شمالی",
            "شماره تلفن": "02188811961", "شهر": "تهران",
            "کد اقتصادی": "411431776417", "شناسه ملی": "10861904730",
            "نام گروه": "نمابر مهر بانکها", "نوع": "حقوقی",
            "شرایط تسویه پیش فرض": "30روزه",
        }
        self.candidate = CustomerMatchCandidate.objects.create(
            source=ExternalSource.ARPA, external_id="400721",
            external_name="بانک سپه شعبه سبلان شمالی",
            customer=self.customer, method="phone", score=Decimal("0.5"),
            payload=self.payload,
        )
        self.user = _user("reviewer", "manager", "sales_team")

    def test_accepting_links_the_party_and_writes_accounting_fields(self):
        customer = crm_merge.accept(self.candidate, self.user)

        self.assertEqual(customer.pk, self.customer.pk)
        self.assertTrue(customer.external_refs.filter(
            source=ExternalSource.ARPA, external_id="400721"
        ).exists())
        customer.refresh_from_db()
        self.assertEqual(customer.economic_code, "411431776417")
        self.assertEqual(customer.payment_terms, "30روزه")

    def test_accepting_does_not_rename_the_account(self):
        """
        The sales team knows customers by the name on their own screen. آرپا's
        legal name is kept on the ref, where the review screen shows it; a
        silent rename mid-quarter is not an update.
        """
        crm_merge.accept(self.candidate, self.user)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name_fa, "بانک سپه سبلان")
        self.assertEqual(
            self.customer.external_refs.get(source=ExternalSource.ARPA).external_name,
            "بانک سپه شعبه سبلان شمالی",
        )

    def test_rejecting_creates_the_account_rather_than_dropping_it(self):
        created = crm_merge.reject(self.candidate, self.user)

        self.assertNotEqual(created.pk, self.customer.pk)
        self.assertEqual(created.name_fa, "بانک سپه شعبه سبلان شمالی")
        self.assertTrue(created.external_refs.filter(external_id="400721").exists())
        self.assertFalse(
            self.customer.external_refs.filter(source=ExternalSource.ARPA).exists()
        )

    def test_a_decision_cannot_be_taken_twice(self):
        crm_merge.accept(self.candidate, self.user)
        with self.assertRaises(crm_merge.MergeError):
            crm_merge.reject(self.candidate, self.user)

    def test_one_decision_settles_the_rival_suggestions(self):
        """
        An «ambig» party is suggested against every customer sharing its name.
        Ruling once answers the question; leaving the rivals pending invites a
        second reviewer to contradict the first.
        """
        other = Customer.objects.create(
            code="didar-co-501", name_fa="بانک سپه سبلان",
            dataset=Dataset.REAL, first_contact_at=timezone.now(),
        )
        rival = CustomerMatchCandidate.objects.create(
            source=ExternalSource.ARPA, external_id="400721",
            external_name="بانک سپه شعبه سبلان شمالی",
            customer=other, method="ambig", score=Decimal(1),
            payload=self.payload,
        )
        crm_merge.accept(self.candidate, self.user)

        rival.refresh_from_db()
        self.assertEqual(rival.state, CustomerMatchCandidate.State.REJECTED)

    def test_a_reviewer_may_choose_a_different_target(self):
        other = Customer.objects.create(
            code="didar-co-502", name_fa="بانک سپه مرکزی",
            dataset=Dataset.REAL, first_contact_at=timezone.now(),
        )
        customer = crm_merge.accept(self.candidate, self.user, other)

        self.assertEqual(customer.pk, other.pk)
        self.assertTrue(other.external_refs.filter(external_id="400721").exists())

    def test_a_code_already_claimed_is_refused_rather_than_moved(self):
        """Silently re-pointing it would undo an earlier reviewer's decision."""
        # A different customer, because the constraint already forbids two
        # suggestions pairing one party with one customer.
        other = Customer.objects.create(
            code="didar-co-503", name_fa="بانک سپه دیگر",
            dataset=Dataset.REAL, first_contact_at=timezone.now(),
        )
        second = CustomerMatchCandidate.objects.create(
            source=ExternalSource.ARPA, external_id="400721",
            external_name="بانک سپه شعبه سبلان شمالی",
            customer=other, method="fuzzy", score=Decimal("0.9"),
            payload=self.payload,
        )
        crm_merge.reject(self.candidate, self.user)
        second.refresh_from_db()
        second.state = CustomerMatchCandidate.State.PENDING
        second.save(update_fields=["state"])
        with self.assertRaises(crm_merge.MergeError):
            crm_merge.accept(second, self.user)


class MergeReviewApiTests(DatasetTestCase):
    """The queue over HTTP, including who is allowed to empty it."""

    def setUp(self):
        super().setUp()
        self.candidate = CustomerMatchCandidate.objects.create(
            source=ExternalSource.ARPA, external_id="400900",
            external_name="شرکت آزمایشی", customer=self.real_customer,
            method="phone", score=Decimal("0.5"),
            payload={"کد": "400900", "نام": "شرکت آزمایشی", "نوع": "حقوقی"},
        )

    def test_the_queue_lists_both_sides_in_one_request(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.get("/api/crm/match-candidates/")
        self.assertEqual(res.status_code, 200)
        row = res.data["results"][0]
        self.assertEqual(row["arpa"]["name_fa"], "شرکت آزمایشی")
        self.assertEqual(row["crm"]["name_fa"], self.real_customer.name_fa)
        # The weight behind the decision, not just the two names.
        self.assertIn("deals", row["crm"])

    def test_the_queue_is_scoped_to_the_account_dataset(self):
        """A candidate against a real customer must not surface in the
        showroom, where accepting it would edit the company's actual file."""
        self.client.force_authenticate(self.ceo)
        self.ceo.crm_dataset = "demo"
        self.ceo.save(update_fields=["crm_dataset"])
        res = self.client.get("/api/crm/match-candidates/")
        self.assertEqual(res.data["count"], 0)

    def test_accepting_over_http_links_the_party(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.post(f"/api/crm/match-candidates/{self.candidate.pk}/accept/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(
            self.real_customer.external_refs.filter(external_id="400900").exists()
        )

    def test_a_second_decision_is_refused_not_silently_applied(self):
        self.client.force_authenticate(self.ceo)
        self.client.post(f"/api/crm/match-candidates/{self.candidate.pk}/accept/")
        res = self.client.post(f"/api/crm/match-candidates/{self.candidate.pk}/reject/")
        self.assertEqual(res.status_code, 409)

    def test_summary_counts_what_is_still_open(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.get("/api/crm/match-candidates/summary/")
        self.assertEqual(res.data["pending"], 1)


class AbsorbTests(APITestCase):
    """
    Fusing two CRM rows that are one company.

    The duplicate is kept and flagged, never deleted. `Deal.customer` cascades,
    so deleting the loser would take its deals, their lines and their stage
    history with it — a tidier list bought with history, and unnoticed until
    someone asks why a customer's numbers dropped.
    """

    def setUp(self):
        now = timezone.now()
        self.primary = Customer.objects.create(
            code="didar-co-700", name_fa="ایران ارقام", dataset=Dataset.REAL,
            first_contact_at=now, phone="",
        )
        self.dupe = Customer.objects.create(
            code="arpa-700", name_fa="شرکت ایران ارقام", dataset=Dataset.REAL,
            first_contact_at=now - timedelta(days=400),
            phone="02142719000", national_id="10100905654",
        )
        self.deal = Deal.objects.create(
            code="didar-d-700", title="معامله", customer=self.dupe,
            dataset=Dataset.REAL, opened_at=now,
        )

    def test_the_survivor_takes_the_records(self):
        crm_merge.absorb(self.primary, self.dupe)

        self.deal.refresh_from_db()
        self.assertEqual(self.deal.customer_id, self.primary.pk)
        self.assertEqual(self.primary.deals.count(), 1)

    def test_the_duplicate_is_flagged_not_deleted(self):
        crm_merge.absorb(self.primary, self.dupe)

        self.dupe.refresh_from_db()
        self.assertEqual(self.dupe.merged_into_id, self.primary.pk)
        self.assertFalse(self.dupe.is_active)
        self.assertTrue(Customer.objects.filter(pk=self.dupe.pk).exists())

    def test_what_only_the_duplicate_knew_is_carried_over(self):
        """
        Two rows usually exist because each system learned something the other
        did not. Keeping only the survivor's blanks throws that away.
        """
        crm_merge.absorb(self.primary, self.dupe)

        self.primary.refresh_from_db()
        self.assertEqual(self.primary.phone, "02142719000")
        self.assertEqual(self.primary.national_id, "10100905654")

    def test_the_relationship_starts_at_the_earlier_of_the_two(self):
        crm_merge.absorb(self.primary, self.dupe)

        self.primary.refresh_from_db()
        self.assertEqual(self.primary.first_contact_at, self.dupe.first_contact_at)

    def test_a_merged_row_cannot_be_merged_again(self):
        crm_merge.absorb(self.primary, self.dupe)
        third = Customer.objects.create(
            code="arpa-701", name_fa="ایران ارقام ۳", dataset=Dataset.REAL,
            first_contact_at=timezone.now(),
        )
        with self.assertRaises(crm_merge.MergeError):
            crm_merge.absorb(third, self.dupe)

    def test_a_customer_cannot_absorb_itself(self):
        with self.assertRaises(crm_merge.MergeError):
            crm_merge.absorb(self.primary, self.primary)

    def test_a_merged_row_leaves_the_customer_list(self):
        crm_merge.absorb(self.primary, self.dupe)
        user = _user("lister", "manager", "sales_team")
        self.client.force_authenticate(user)

        names = [
            r["name_fa"]
            for r in self.client.get("/api/crm/customers/").data["results"]
        ]
        self.assertIn("ایران ارقام", names)
        self.assertNotIn("شرکت ایران ارقام", names)


class BulkReviewTests(APITestCase):
    """Sending customers from the list into the merge queue."""

    def setUp(self):
        now = timezone.now()
        self.a = Customer.objects.create(
            code="didar-co-800", name_fa="پارس رول", dataset=Dataset.REAL,
            first_contact_at=now, phone="02155551234",
        )
        self.b = Customer.objects.create(
            code="arpa-800", name_fa="شرکت پارس رول", dataset=Dataset.REAL,
            first_contact_at=now, phone="02155551234",
        )
        self.c = Customer.objects.create(
            code="arpa-801", name_fa="هیچ‌کس", dataset=Dataset.REAL,
            first_contact_at=now,
        )
        self.user = _user("bulk", "manager", "sales_team")
        self.client.force_authenticate(self.user)

    def test_two_selected_rows_are_queued_as_a_pair(self):
        res = self.client.post(
            "/api/crm/customers/bulk-review/", {"ids": [self.a.pk, self.b.pk]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["queued"], 1)
        candidate = CustomerMatchCandidate.objects.get(source=ExternalSource.CRM)
        self.assertEqual(
            {candidate.customer_id, candidate.duplicate_id}, {self.a.pk, self.b.pk}
        )

    def test_the_same_pair_is_not_queued_twice(self):
        """
        Selecting the pair the other way round is the same question. Two rows
        would mean two reviewers ruling separately, and nothing stopping them
        from disagreeing.
        """
        for ids in ([self.a.pk, self.b.pk], [self.b.pk, self.a.pk]):
            self.client.post(
                "/api/crm/customers/bulk-review/", {"ids": ids}, format="json"
            )
        self.assertEqual(
            CustomerMatchCandidate.objects.filter(source=ExternalSource.CRM).count(), 1
        )

    def test_one_selected_row_makes_the_matcher_hunt_for_its_twin(self):
        res = self.client.post(
            "/api/crm/customers/bulk-review/", {"ids": [self.b.pk]}, format="json"
        )
        self.assertEqual(res.data["queued"], 1)
        candidate = CustomerMatchCandidate.objects.get(source=ExternalSource.CRM)
        self.assertEqual(
            {candidate.customer_id, candidate.duplicate_id}, {self.a.pk, self.b.pk}
        )

    def test_a_row_with_no_twin_is_reported_not_silently_dropped(self):
        res = self.client.post(
            "/api/crm/customers/bulk-review/",
            {"ids": [self.c.pk, self.a.pk, self.b.pk]}, format="json",
        )
        reasons = [s["reason"] for s in res.data["skipped"]]
        self.assertTrue(any("پیدا نشد" in r for r in reasons), res.data)

    def test_queueing_never_merges_on_its_own(self):
        """
        Even an exact name match only queues. Across two systems a repeated
        name means one company; inside one file it more often means someone
        typed it twice, and the person who pressed the button can say which.
        """
        self.client.post(
            "/api/crm/customers/bulk-review/", {"ids": [self.a.pk, self.b.pk]},
            format="json",
        )
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertIsNone(self.a.merged_into_id)
        self.assertIsNone(self.b.merged_into_id)

    def test_accepting_a_crm_pair_fuses_the_two_rows(self):
        self.client.post(
            "/api/crm/customers/bulk-review/", {"ids": [self.a.pk, self.b.pk]},
            format="json",
        )
        candidate = CustomerMatchCandidate.objects.get(source=ExternalSource.CRM)
        res = self.client.post(f"/api/crm/match-candidates/{candidate.pk}/accept/")
        self.assertEqual(res.status_code, 200, res.data)

        self.b.refresh_from_db()
        self.assertEqual(self.b.merged_into_id, self.a.pk)

    def test_rejecting_a_crm_pair_creates_nothing(self):
        """Both sides already exist, so «different customers» is just the
        answer — there is no party to file and no account to invent."""
        self.client.post(
            "/api/crm/customers/bulk-review/", {"ids": [self.a.pk, self.b.pk]},
            format="json",
        )
        before = Customer.objects.count()
        candidate = CustomerMatchCandidate.objects.get(source=ExternalSource.CRM)
        self.client.post(f"/api/crm/match-candidates/{candidate.pk}/reject/")

        self.assertEqual(Customer.objects.count(), before)
        self.b.refresh_from_db()
        self.assertIsNone(self.b.merged_into_id)


class BulkDeleteTests(APITestCase):
    """
    Deleting from the list, and refusing to when it would cost history.

    `Deal.customer` cascades and `SalesInvoice.customer` is PROTECT, so a
    naive bulk delete either destroys deals silently or dies halfway with a
    database error naming no row. Both are worse than saying which customers
    could not go, and why.
    """

    def setUp(self):
        now = timezone.now()
        self.empty = Customer.objects.create(
            code="arpa-900", name_fa="بی‌سابقه", dataset=Dataset.REAL,
            first_contact_at=now,
        )
        self.with_deal = Customer.objects.create(
            code="arpa-901", name_fa="با معامله", dataset=Dataset.REAL,
            first_contact_at=now,
        )
        Deal.objects.create(
            code="d-901", title="م", customer=self.with_deal,
            dataset=Dataset.REAL, opened_at=now,
        )
        self.with_invoice = Customer.objects.create(
            code="arpa-902", name_fa="با فاکتور", dataset=Dataset.REAL,
            first_contact_at=now,
        )
        SalesInvoice.objects.create(
            code="arpa-inv-902", number="902", customer=self.with_invoice,
            issued_at=now.date(), amount_rial=1000, dataset=Dataset.REAL,
        )
        self.client.force_authenticate(_user("deleter", "manager", "sales_team"))

    def _delete(self, *rows):
        return self.client.post(
            "/api/crm/customers/bulk-delete/",
            {"ids": [r.pk for r in rows]}, format="json",
        )

    def test_an_empty_customer_is_deleted(self):
        res = self._delete(self.empty)
        self.assertEqual(res.data["deleted"], 1)
        self.assertFalse(Customer.objects.filter(pk=self.empty.pk).exists())

    def test_history_blocks_the_delete_and_says_what_held_it(self):
        res = self._delete(self.with_deal, self.with_invoice)

        self.assertEqual(res.data["deleted"], 0)
        self.assertTrue(Customer.objects.filter(pk=self.with_deal.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=self.with_invoice.pk).exists())
        reasons = {b["name_fa"]: b["reason"] for b in res.data["blocked"]}
        self.assertIn("معامله", reasons["با معامله"])
        self.assertIn("فاکتور", reasons["با فاکتور"])

    def test_a_mixed_selection_deletes_what_it_can(self):
        """A refusal on one row must not strand the rest — a reviewer clearing
        1,600 dormant accounts cannot be made to retry them one at a time."""
        res = self._delete(self.empty, self.with_deal)

        self.assertEqual(res.data["deleted"], 1)
        self.assertEqual(len(res.data["blocked"]), 1)
        self.assertFalse(Customer.objects.filter(pk=self.empty.pk).exists())
        self.assertTrue(Customer.objects.filter(pk=self.with_deal.pk).exists())

    def test_an_empty_selection_is_refused(self):
        res = self.client.post(
            "/api/crm/customers/bulk-delete/", {"ids": []}, format="json"
        )
        self.assertEqual(res.status_code, 400)
