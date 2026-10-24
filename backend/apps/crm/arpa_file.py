"""
Read an آرپا export — the file someone downloads and uploads, as it is.

آرپا saves «خروجی اکسل» as SYLK (`.slk`), Excel's old text format, and that is
what arrives; an `.xlsx` re-saved from Excel is accepted too. There is no
Excel on the server, so SYLK is decoded here.

The one hard part is the text. آرپا writes Windows-1256 bytes, and SYLK can
only carry ASCII, so every byte above 0x7F is wrapped in an escape that
spells the *Latin-1* character with that byte value:

* ``ESC N <accent> <letter>`` — an accented Latin letter, accent as in
  ISO 6937 (``ESC N K C`` is Ç, byte C7, which in 1256 is «ا»);
* ``ESC N <c>`` — an ISO 6937 character at ``0x80 + c`` (``ESC N i`` is Ø,
  byte D8, «ط»);
* ``ESC <a> <b>`` — the byte itself, as two nibbles: ``(a-0x20) << 4 |
  (b-0x30)`` (``ESC ) 8`` is 0x98, «ک»).

Undo the escape, get the byte, decode the bytes as 1256. Checked against
Excel's own reading of two real exports: every text cell identical.
"""
from __future__ import annotations

import io
import re
import unicodedata

#: ISO 6937 accent bytes C1..CF, as SYLK writes them after ``ESC N``.
ACCENTS = {
    "A": "̀",  # grave
    "B": "́",  # acute
    "C": "̂",  # circumflex
    "D": "̃",  # tilde
    "E": "̄",  # macron
    "F": "̆",  # breve
    "G": "̇",  # dot above
    "H": "̈",  # diaeresis
    "J": "̊",  # ring
    "K": "̧",  # cedilla
    "M": "̋",  # double acute
    "N": "̨",  # ogonek
    "O": "̌",  # caron
}

#: ISO 6937 characters at A0..FF that exist in Latin-1, by ``chr(code-0x80)``.
SINGLE = {
    "!": "¡", '"': "¢", "#": "£", "%": "¥", "'": "§", "(": "¤", "+": "«",
    "0": "°", "1": "±", "2": "²", "3": "³", "4": "×", "5": "µ", "6": "¶",
    "7": "·", "8": "÷", ";": "»", "<": "¼", "=": "½", ">": "¾", "?": "¿",
    "a": "Æ", "b": "Ð", "c": "ª", "i": "Ø", "k": "º", "l": "Þ",
    "q": "æ", "s": "ð", "y": "ø", "{": "ß", "|": "þ",
}

_TOKEN = re.compile(r"\x1bN([A-O])(.)|\x1bN(.)|\x1b(.)(.)", re.S)


class ArpaFileError(ValueError):
    """The upload is not a sheet this reader understands."""


def _unescape(text: str) -> str:
    """SYLK text (read as Latin-1) back to the Persian آرپا wrote."""
    if "\x1b" not in text:
        return text

    def one(m: re.Match) -> str:
        accent, base, single, hi, lo = m.groups()
        if accent:
            ch = unicodedata.normalize("NFC", base + ACCENTS[accent])
            return ch if len(ch) == 1 else base
        if single:
            return SINGLE.get(single, "?")
        return chr(((ord(hi) - 0x20) << 4) | (ord(lo) - 0x30))

    latin = _TOKEN.sub(one, text)
    return latin.encode("latin-1", "replace").decode("cp1256", "replace")


def _value(raw: str):
    """A SYLK ``K`` value: quoted text, a number, or a formula's result."""
    if raw.startswith('"'):
        return _unescape(raw[1:-1].replace('""', '"') if raw.endswith('"') else raw[1:])
    try:
        n = float(raw)
    except ValueError:
        return _unescape(raw)
    return int(n) if n.is_integer() else n


def read_sylk(data: bytes) -> list[list]:
    # آرپا's own file is pure ASCII (every Persian byte escaped), which
    # decodes the same either way. One re-saved by another program may carry
    # the text raw — as UTF-8, or as 1256 bytes — and is read as that.
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1256", "replace")
    if not text.startswith("ID;"):
        raise ArpaFileError("فایل SYLK معتبر نیست.")
    cells: dict[tuple[int, int], object] = {}
    row = col = 1
    for line in text.splitlines():
        kind, _, rest = line.partition(";")
        if kind not in ("C", "F"):
            continue
        # A field can contain «;» only inside the K value, which is last.
        fields = rest.split(";")
        value = None
        for i, part in enumerate(fields):
            tag = part[:1]
            if tag == "Y":
                row = int(part[1:] or row)
            elif tag == "X":
                col = int(part[1:] or col)
            elif tag == "K" and kind == "C":
                value = _value(";".join(fields[i:])[1:])
                break
        if kind == "C" and value is not None:
            cells[(row, col)] = value
    if not cells:
        return []
    n_rows = max(r for r, _ in cells)
    n_cols = max(c for _, c in cells)
    return [[cells.get((r, c)) for c in range(1, n_cols + 1)] for r in range(1, n_rows + 1)]


def read_xlsx(data: bytes) -> list[list]:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # zip/xml errors all mean «not an xlsx»
        raise ArpaFileError("فایل اکسل خوانده نشد.") from exc
    rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    wb.close()
    return rows


def read_sheet(data: bytes, filename: str = "") -> list[list]:
    """The first sheet as rows of cells, whatever آرپا or Excel saved."""
    name = filename.lower()
    if data[:3] == b"ID;" or name.endswith(".slk"):
        return read_sylk(data)
    if data[:2] == b"PK" or name.endswith(".xlsx"):
        return read_xlsx(data)
    raise ArpaFileError("فقط خروجی آرپا (.slk) یا فایل اکسل (.xlsx) پذیرفته می‌شود.")
