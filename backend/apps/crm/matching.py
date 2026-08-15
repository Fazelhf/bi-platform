"""
Deciding whether two customer records are the same customer.

Two systems hold the company's customer file and neither was written with the
other in mind: دیدار (the old CRM) and آرپا (accounting). Merging them is the
whole problem, and the shape of the data — measured on the real exports before
any of this was written — rules out the obvious approaches:

* **There is no shared key.** دیدار carries no شناسه ملی on any of its 2,717
  rows. آرپا has one on 22% of its parties. The identifier that would have
  settled every case simply is not there.

* **Phone numbers are not identities.** «پلی کلینیک سوم خرداد خرمشهر» and
  «شبکه بهداشت و درمان خرمشهر» answer the same switchboard. So do a hospital
  and the person who buys for it. 55 of 138 active buyers pair up this way and
  a good share of those pairs are wrong.

* **Similar names are routinely different customers.** «بانک کشاورزی ایلام»
  and «بانک کشاورزی گیلان» are 86% alike by character overlap and are branches
  in provinces 900km apart. A bank with a branch in every province turns
  string similarity into a trap.

What survives: an **exactly equal normalised name** is strong enough to merge
on unattended. Everything else is a suggestion for a human. That is not
timidity — a wrong merge silently fuses two customers' order history, and
nobody discovers it by looking at a screen.

Normalisation matters more than the ladder does. آرپا writes legacy Persian
(Arabic ي U+064A and ك U+0643); دیدار writes ی and ک. Compared byte for byte,
almost nothing matches — the folding below is what makes the exact-name tier
work at all.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Characters that differ between the two systems' encodings but not to a
#: reader. Folded before anything else touches the string.
_FOLD = {
    "ي": "ی",  # ي  Arabic yeh      → ی
    "ى": "ی",  # ى  alef maksura    → ی
    "ك": "ک",  # ك  Arabic kaf      → ک
    "ة": "ه",  # ة  teh marbuta     → ه
    "ؤ": "و",  # ؤ                  → و
    "ھ": "ه",  # ھ                  → ه
    # Hamza is written or dropped according to taste: آرپا's «مهدیس موءمنی»
    # is the CRM's «مهدیس مومنی», and left in place the two are two people.
    "ء": "",
    "أ": "ا",
    "إ": "ا",
    "ئ": "ی",
    "‌": " ",       # ZWNJ — «نمابر‌مهر» and «نمابر مهر» are one name
    "‎": "",
    "‏": "",
}
for _i, _d in enumerate("۰۱۲۳۴۵۶۷۸۹"):
    _FOLD[_d] = str(_i)
for _i, _d in enumerate("٠١٢٣٤٥٦٧٨٩"):
    _FOLD[_d] = str(_i)

_HARAKAT = re.compile(r"[ً-ْ]")

#: Words that describe a company without identifying it. «شرکت الف» and «الف»
#: are one customer; leaving these in means the same firm fails to match
#: itself across two systems that disagree about how formal to be.
_NOISE = (
    "سهامی خاص", "سهامی عام", "با مسئولیت محدود", "مسئولیت محدود",
    "شرکت", "تعاونی", "بازرگانی", "تولیدی", "صنایع", "صنعتی", "گروه",
    "مهندسی", "خدمات", "فروشگاه", "موسسه", "کارخانه", "نمایندگی",
    "پخش", "توزیع", "آقای", "اقای", "خانم", "جناب", "سرکار", "حاج",
    "دکتر", "مهندس",
)

#: Place names that appear as branch suffixes. Two names that agree on
#: everything *except* one of these are the same organisation in different
#: cities — which is a different customer, with a different buyer and a
#: different invoice history. This is the guard that stops «بانک کشاورزی
#: ایلام» from being merged into «بانک کشاورزی گیلان».
_PLACES = frozenset("""
تهران البرز کرج اصفهان فارس شیراز خراسان رضوی مشهد شمالی جنوبی بجنورد بیرجند
آذربایجان شرقی غربی تبریز ارومیه اردبیل گیلان رشت مازندران ساری گلستان گرگان
قزوین قم مرکزی اراک زنجان سمنان کرمان کرمانشاه کردستان سنندج ایلام لرستان
خرم‌آباد خرم آباد همدان یزد بوشهر هرمزگان بندرعباس سیستان بلوچستان زاهدان
چهارمحال بختیاری شهرکرد کهگیلویه بویراحمد یاسوج خوزستان اهواز خرمشهر آبادان
اردکان کاشان قشم کیش نجف‌آباد ورامین اسلامشهر شهریار
""".split())


def fold(value) -> str:
    """Normalise script, digits and whitespace. The base for every key."""
    text = "".join(_FOLD.get(ch, ch) for ch in str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = _HARAKAT.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def name_key(value) -> str:
    """
    A name reduced to what identifies it.

    Noise words out, punctuation out, order preserved. Two records with the
    same key are the same customer as far as this module is willing to claim
    without a human.
    """
    text = fold(value)
    for word in _NOISE:
        text = re.sub(rf"(?:^|\s){re.escape(word)}(?=\s|$)", " ", text)
    text = re.sub(r"[^\w\s؀-ۿ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def phone_key(value) -> str:
    """
    The last eight significant digits.

    Enough to see through «02144641330», «44641330» and «021-4464-1330»
    without pretending that a shared switchboard means a shared identity —
    that judgement belongs to the caller, not to the key.
    """
    digits = re.sub(r"\D", "", fold(value)).lstrip("0")
    return digits[-8:] if len(digits) >= 8 else ""


def id_key(value) -> str:
    """شناسه ملی / کد ملی / کد اقتصادی, or "" if it is not one."""
    digits = re.sub(r"\D", "", fold(value))
    return digits if 10 <= len(digits) <= 14 else ""


def places(value) -> frozenset[str]:
    """Which place names a name mentions."""
    return frozenset(name_key(value).split()) & _PLACES


def place_conflict(left, right) -> bool:
    """
    True when the two names name *different* places.

    Silence on either side is not a conflict: «بانک سینا» and «بانک سینا
    تهران» may well be one account. Two named and differing places is.
    """
    a, b = places(left), places(right)
    return bool(a and b and not (a & b))


def similarity(left, right) -> float:
    return SequenceMatcher(None, name_key(left), name_key(right)).ratio()


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------
class Method:
    """How a pairing was arrived at. Mirrors CustomerMatchCandidate.Method."""

    EXISTING = "existing"    # already linked by a previous run
    NATIONAL_ID = "nid"
    BRANCH = "branch"        # same national id, different place — see below
    NAME = "name"
    AMBIGUOUS = "ambig"      # the name matches — and matches more than one
    PHONE = "phone"
    FUZZY = "fuzzy"
    NONE = "none"


#: Tiers trusted enough to write without asking. Deliberately short — and
#: shorter than it first was.
#:
#: `NATIONAL_ID` used to be here, on the reasoning that a شناسه ملی names one
#: legal entity. It does. It is the customers that are not entities: they are
#: branches, and every branch of پست بانک carries the head office's number. In
#: practice the tier merged twenty-three separate branches into one another —
#: «پست بانک کرمان», «پست بانک زنجان» and fifteen more into «دولتی پست بانک»,
#: two hospitals into «اداره کل درمان تامین اجتماعی».
#:
#: Guarding it by place only narrowed the damage, because a head-office record
#: names no place and so never disagrees with anything.
#:
#: What settled it: دیدار holds no national id on any of its 2,717 rows, so
#: this tier can never link the two systems — the merge it exists for. Its
#: only reachable effect is joining آرپا parties to each other, which is the
#: bug. It stays in the ladder as a suggestion and writes nothing.
AUTO = frozenset({Method.EXISTING, Method.NAME})

#: Below this, a name pair is not even worth a reviewer's attention.
FUZZY_FLOOR = 0.86


@dataclass(frozen=True)
class Match:
    method: str
    customer_id: int | None
    score: float = 0.0

    @property
    def is_auto(self) -> bool:
        return self.method in AUTO

    @property
    def found(self) -> bool:
        return self.customer_id is not None


class CustomerIndex:
    """
    Every existing customer, indexed by each key the ladder consults.

    Built once per import. `add` keeps it current as new customers are
    created, so two spellings of a new party inside one run collapse onto the
    row the first of them created instead of making two.
    """

    def __init__(self):
        self.by_ref: dict[tuple[str, str], int] = {}
        self.by_nid: dict[str, int] = {}
        self.by_name: dict[str, list[int]] = {}
        self.by_phone: dict[str, list[int]] = {}
        self.names: dict[int, str] = {}

    # -- building --------------------------------------------------------
    def add(self, customer_id: int, *, name: str = "", nids=(), phones=()) -> None:
        self.names[customer_id] = name
        key = name_key(name)
        if key:
            self.by_name.setdefault(key, []).append(customer_id)
        for value in nids:
            k = id_key(value)
            # First writer wins: an id already claimed is not silently
            # reassigned, because the reassignment would be invisible.
            if k:
                self.by_nid.setdefault(k, customer_id)
        for value in phones:
            k = phone_key(value)
            if k:
                self.by_phone.setdefault(k, []).append(customer_id)

    def add_ref(self, source: str, external_id: str, customer_id: int) -> None:
        self.by_ref[(source, str(external_id))] = customer_id

    # -- asking ----------------------------------------------------------
    def find(self, *, source, external_id, name, nids=(), phones=()) -> Match:
        """
        Walk the ladder, strongest first, and stop at the first rung that
        answers. The rung is returned along with the answer so the caller can
        tell a merge from a suggestion.
        """
        linked = self.by_ref.get((source, str(external_id)))
        if linked is not None:
            return Match(Method.EXISTING, linked, 1.0)

        for value in nids:
            k = id_key(value)
            if k and k in self.by_nid:
                other = self.by_nid[k]
                # A شناسه ملی identifies a *legal entity*, and the customers
                # here are largely its branches: every branch of بانک صادرات
                # shares the head office's number. Trusting the id alone
                # merged «بانک صادرات کرمانشاه» into «بانک صادرات آذربایجان»
                # — the exact failure this ladder exists to prevent, arriving
                # through its most-trusted rung.
                #
                # So the id still finds the pair, but when the two names give
                # different places it is a branch, not a duplicate, and a
                # person decides.
                if place_conflict(name, self.names.get(other, "")):
                    return Match(Method.BRANCH, other, 0.6)
                return Match(Method.NATIONAL_ID, other, 1.0)

        key = name_key(name)
        exact = self.by_name.get(key) if key else None
        if exact:
            if len(set(exact)) == 1:
                return Match(Method.NAME, exact[0], 1.0)
            # The name matches, and matches more than one customer — which
            # means the CRM already holds a duplicate under that name. Merging
            # into either half would bury the duplicate instead of surfacing
            # it, and the reviewer's first move here is to fix *that*, not to
            # rule on this party. Reported as its own tier for exactly that
            # reason.
            return Match(Method.AMBIGUOUS, exact[0], 1.0)

        for value in phones:
            k = phone_key(value)
            hits = self.by_phone.get(k) if k else None
            if hits:
                return Match(Method.PHONE, hits[0], 0.5)

        return self._fuzzy(name)

    def _fuzzy(self, name) -> Match:
        key = name_key(name)
        if not key:
            return Match(Method.NONE, None)
        # Only names sharing an opening — comparing against all of them is
        # both slow and a good way to find nonsense.
        head = key[:4]
        best_id, best_score = None, 0.0
        for other, ids in self.by_name.items():
            if not other.startswith(head):
                continue
            score = SequenceMatcher(None, key, other).ratio()
            if score > best_score:
                best_id, best_score = ids[0], score
        if best_id is None or best_score < FUZZY_FLOOR:
            return Match(Method.NONE, None)
        if place_conflict(name, self.names.get(best_id, "")):
            return Match(Method.NONE, None)
        return Match(Method.FUZZY, best_id, best_score)
