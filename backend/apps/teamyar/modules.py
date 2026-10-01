"""
ماژول‌های تیمیار — what the rollout delivers, one module at a time.

The modules are rows management can add to, not a fixed list: the charter
names twelve business lines (seeded by migration from `CHARTER` below), and
Teamyar splits some of them further — «پست و پیامک», «حقوق و دستمزد» — as
the work goes on.

Activities and meetings are filed under a module by title when nobody picks
one: «راه اندازی ماژول شعبه» and «جلسه آموزش ماژول پرسنلی» say which module
they belong to, so the module view fills itself from what is already typed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

YEAR = 1405
PM = "فاضل حافظی"

#: Teamyar's side of the project, from the charter's role table — offered in
#: the attendee picker next to our own staff.
TEAMYAR_TEAM = [
    ("مهدی بهزادی", "مدیر استقرار و پشتیبانی"),
    ("فهیمه خراسانی", "مدیر پروژه · اتوماسیون اداری"),
    ("شکیبا خلج", "اتوماسیون اداری · CRM و پروژه"),
    ("سید وحید ابراهیمی", "مالی و حسابداری · دارایی و بهای تمام شده"),
    ("علی منصف", "زنجیره تامین · فروش"),
    ("فاطمه علی اکبر", "تولید · تعمیرات و نگهداری"),
    ("حمیرا رودکی", "شعبه · منابع انسانی"),
]


@dataclass(frozen=True)
class CharterModule:
    key: str
    title: str
    owner: str          # our manager of the unit
    specialist: str     # Teamyar's specialist for it
    workshop: int       # charter Gantt: month of the workshop
    test_server: tuple  # charter Gantt: months on the test server
    keywords: tuple


CHARTER = [
    CharterModule("branch", "مدیریت سازمانی (شعبه)", PM, "حمیرا رودکی", 6, (7, 8),
                  ("شعبه", "مدیریت سازمانی")),
    CharterModule("hr", "منابع انسانی و پرسنلی", "بهزاد فرزانه", "حمیرا رودکی", 6, (7, 8),
                  ("پرسنلی", "منابع انسانی", "سرمایه انسانی", "حقوق و دستمزد", "حضور و غیاب")),
    CharterModule("office", "اتوماسیون اداری", "شیده شامحمدی", "فهیمه خراسانی", 7, (7, 8),
                  ("اتوماسیون", "پست و پیامک", "پیامک", "دبیرخانه", "مکاتبات", "نامه")),
    CharterModule("crm", "CRM", "امیر عصاری", "شکیبا خلج", 7, (7, 8),
                  ("crm", "ارتباط با مشتری", "تجربه مشتری", "باشگاه مشتری")),
    CharterModule("sales", "فروش", "امیر عصاری", "علی منصف", 7, (8, 9),
                  ("فروش", "پیش فاکتور", "بازرگانی")),
    CharterModule("costing", "بهای تمام شده", "شهرام شاه آبادی", "سید وحید ابراهیمی", 7, (8, 9),
                  ("بهای تمام شده", "قیمت تمام شده")),
    CharterModule("supply", "زنجیره تامین (خرید و انبار)", "زهرا کوهنورد", "علی منصف", 7, (9, 10),
                  ("زنجیره تامین", "خرید", "انبار", "تدارکات", "تامین کالا")),
    CharterModule("project", "مدیریت پروژه", PM, "شکیبا خلج", 7, (9, 10),
                  ("ماژول پروژه", "مدیریت پروژه")),
    CharterModule("finance", "مالی و حسابداری", "شهرام شاه آبادی", "سید وحید ابراهیمی", 7, (9, 10),
                  ("حسابداری", "کدینگ", "مالی", "خزانه")),
    CharterModule("production", "تولید", "محمد مهدی سیفی", "فاطمه علی اکبر", 7, (9, 10),
                  ("تولید", "کارخانه", "bom")),
    CharterModule("assets", "اموال و دارایی", "شهرام شاه آبادی", "سید وحید ابراهیمی", 7, (9, 10),
                  ("اموال", "دارایی ثابت", "دارایی")),
    CharterModule("maintenance", "تعمیر و نگهداری (نت)", "محمد مهدی سیفی", "فاطمه علی اکبر", 7, (9, 10),
                  ("تعمیر", "نگهداری", "نت")),
]


def norm(text: str) -> str:
    """Folded words with a space at both ends, so `in` matches whole words."""
    from apps.core.excel_import import fold

    return f" {re.sub(r'[^\w]+', ' ', fold(text).lower()).strip()} "


def keywords_of(module) -> list[str]:
    """A module's own title counts as a keyword, then whatever was listed."""
    words = [module.title, re.sub(r"\(.*?\)", "", module.title)]
    words += [w for w in re.split(r"[،,\n]", module.keywords or "")]
    return [k for k in (norm(w) for w in words) if k.strip()]


def guess(modules, *texts: str):
    """
    The module a title names, or None. Whole words only («مالی» is not in
    «اجمالی») and the longest keyword wins: «بهای تمام شده» over «مالی»,
    «منابع انسانی» over anything shorter inside it.
    """
    hay = " ".join(norm(t) for t in texts if t)
    best, best_len = None, 0
    for m in modules:
        for k in keywords_of(m):
            if k in hay and len(k) > best_len:
                best, best_len = m, len(k)
    return best
