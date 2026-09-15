"""
Telling «شیما نظام آبادی» and «شیما نظام ابادی» are the same person.

Names reached the database from Excel, from the CRM import and from people
typing, so the same name arrives with Arabic or Persian ی and ک, with or
without آ, and with a space or a نیم‌فاصله in different places. Comparing
the raw strings is what let one person become two.
"""
import re

_LETTERS = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا",
})
_GAPS = re.compile(r"[\s‌‍‎‏]+")


def normalize(name: str | None) -> str:
    """A comparison key — never shown, never stored."""
    return _GAPS.sub("", (name or "").translate(_LETTERS)).strip()


def clean(name: str | None) -> str:
    """How a name is stored: trimmed, with runs of spaces collapsed."""
    return re.sub(r"\s+", " ", (name or "").strip())
