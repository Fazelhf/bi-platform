"""
برنامه‌ی منشور — the rollout plan exactly as the signed charter lays it out
(«منشور پروژه استقرار کاغذ حساس نمابر», ۱۴۰۵/۰۶/۲۸). It is the sample of
the activities' Excel import, so a fresh plan starts from the document both
companies agreed to instead of being typed in bar by bar.

Each activity's span is the months shaded for it in the charter's Gantt: it
starts on the first of its first month and ends on the last day of its last.
Three rows carry no shading in the charter (BPML, tests, end-user training)
and hypercare is not in the Gantt at all; their months are placed in order
and say so in their description.

Owners are written as names, like everywhere on this page: «R/A» is almost
always Teamyar's specialist, so the owner reads «specialist (تیمیار) / our
manager of that unit».
"""
from __future__ import annotations

from datetime import date

from apps.core import jalali

from .modules import CHARTER as MODULES, PM, YEAR

ROLES = ("مدیرعامل", "مدیر پروژه ERP", "کاربران کلیدی واحد", "مدیر واحد",
         "مدیر استقرار تیمیار", "تحلیلگر کسب‌وکار تیمیار", "متخصص تیمیار")

PHASES = [
    ("آماده‌سازی", "#6366f1"),
    ("کاوش — کارگاه‌های آموزشی", "#0ea5e9"),
    ("کاوش — مستندات و برنامه تست", "#8b5cf6"),
    ("تحقق — پیاده‌سازی روی سرور تستی", "#f59e0b"),
    ("تحقق — تست و آموزش", "#ec4899"),
    ("استقرار — انتقال به سرور اصلی", "#10b981"),
    ("پشتیبانی هایپرکر", "#14b8a6"),
]

ASSUMED = "در گانت منشور ماهش علامت نخورده؛ به ترتیب فازها گذاشته شد."


def _start(m: int) -> date:
    return jalali.to_gregorian(YEAR, m, 1)


def _end(m: int) -> date:
    return jalali.to_gregorian(YEAR, m, jalali.month_days(YEAR, m))


def _raci(code: str) -> str:
    out: dict[str, list[str]] = {}
    for role, c in zip(ROLES, code.split()):
        out.setdefault(c, []).append(role)
    return " · ".join(f"{k}: {'، '.join(out[k])}" for k in ("R/A", "R", "A", "C", "I") if k in out)


def _owner(specialist: str, ours: str) -> str:
    return f"{specialist} (تیمیار) / {ours}" if specialist else ours


def plan() -> list[dict]:
    """Every row of the charter, in Gantt order. `after` names the row it waits on."""
    rows: list[dict] = []

    def add(phase, title, owner, months, raci="", note="", after="", milestone=False, done=False, end=None,
            module=""):
        first, last = months[0], months[-1]
        lines = [f"گانت منشور: ماه {'–'.join(f'{m:02d}' for m in months)}/{YEAR}"]
        if raci:
            lines.append(_raci(raci))
        if note:
            lines.append(note)
        finish = end or _end(last)
        rows.append({
            "phase": PHASES[phase][0], "title": title, "owner": owner,
            "start_on": finish if milestone else _start(first), "end_on": finish,
            "is_milestone": milestone, "done": done, "after": after, "module": module,
            "description": "\n".join(lines),
        })

    add(0, "تهیه منشور پروژه", "تحلیلگر کسب‌وکار تیمیار / " + PM, [6], "I C I I C R/A I",
        done=True, end=jalali.to_gregorian(YEAR, 6, 28))
    add(0, "تأیید و امضای منشور پروژه", PM, [6], milestone=True, done=True,
        end=jalali.to_gregorian(YEAR, 6, 28), after="تهیه منشور پروژه")
    add(0, "آماده‌سازی سرور دمو برای کارگاه‌ها", "مهدی بهزادی (تیمیار) / " + PM, [6], "I I I I C A R")

    for mod in MODULES:
        add(1, f"کارگاه آموزشی {mod.title}", _owner(mod.specialist, mod.owner), [mod.workshop],
            "I I C C I C R/A", after="آماده‌سازی سرور دمو برای کارگاه‌ها", module=mod.title)

    add(2, "لیست اصلی فرایندهای کسب‌وکار (BPML)", "فهیمه خراسانی (تیمیار) / " + PM, [8],
        "I C C C C R/A C", ASSUMED)
    add(2, "سند نیازمندی‌های کسب‌وکار (BRD) شامل لیست WRICEF", "فهیمه خراسانی (تیمیار) / " + PM, [8],
        "I C C C C R/A C", after="لیست اصلی فرایندهای کسب‌وکار (BPML)")
    add(2, "پایان کاوش — تحویل BPML و BRD", PM, [8], milestone=True,
        after="سند نیازمندی‌های کسب‌وکار (BRD) شامل لیست WRICEF")
    add(2, "آماده‌سازی برنامه تست و تست‌کیس‌ها", "تیمیار / " + PM, [8, 9], "I C I I I C R/A")

    for mod in MODULES:
        add(3, f"پیکربندی و انتقال داده‌ی {mod.title} روی سرور تستی", _owner(mod.specialist, mod.owner),
            list(mod.test_server), "I I C C C C R/A", after=f"کارگاه آموزشی {mod.title}", module=mod.title)
    add(3, "پایان پیاده‌سازی روی سرور تستی", PM, [10], milestone=True)

    add(4, "اجرای روش‌های مختلف تست", "تیمیار / " + PM, [10], "I C C C I C R/A", ASSUMED,
        after="آماده‌سازی برنامه تست و تست‌کیس‌ها")
    add(4, "آموزش کاربران نهایی و گرفتن بازخورد", "تیمیار / " + PM, [10], "I C C C I I R/A", ASSUMED)

    for mod in MODULES:
        add(5, f"انتقال {mod.title} به سرور اصلی", _owner(mod.specialist, mod.owner), [11, 12],
            "I I I I C C R/A", after=f"پیکربندی و انتقال داده‌ی {mod.title} روی سرور تستی", module=mod.title)
    add(5, "Go-live — استقرار کامل روی سرور اصلی", PM, [12], milestone=True)

    add(6, "پشتیبانی هایپرکر پس از استقرار", "مهدی بهزادی (تیمیار) / " + PM, [12], "I I I I C I R/A",
        "در گانت منشور نیامده؛ پس از انتقال به سرور اصلی گذاشته شد.")
    return rows


def key(text) -> str:
    """Title matching that ignores spacing, half-spaces and Arabic letters."""
    from apps.core.excel_import import fold

    return fold(text).replace(" ", "")

