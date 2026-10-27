"""
Scan the customer file for duplicates and queue them for review.

    manage.py crm_dedupe_scan --dry-run --xlsx dupes.xlsx   # count + report only
    manage.py crm_dedupe_scan                               # queue in «بازبینی تطبیق»

Never merges. A queued pair waits for a person in the review screen.
"""
from django.core.management.base import BaseCommand

from apps.crm import merge as crm_merge
from apps.crm.models import Dataset


def _source(code: str) -> str:
    return (code or "").split("-")[0] or "crm"


class Command(BaseCommand):
    help = "Find suspected duplicate customers (definite / suspect) and queue them for review."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count and report; queue nothing.")
        parser.add_argument("--xlsx", help="Write the pair report to this workbook.")

    def handle(self, *args, dry_run=False, xlsx=None, **opts):
        pairs, crowded = crm_merge.find_pairs(Dataset.REAL)
        definite = sum(1 for p in pairs if p["confidence"] == "definite")
        if xlsx:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = "جفت‌های تکراری"
            ws.sheet_view.rightToLeft = True
            ws.append(["اطمینان", "معیار", "شناسه ۱", "کد ۱", "منبع ۱", "نام ۱",
                       "شناسه ۲", "کد ۲", "منبع ۲", "نام ۲"])
            for p in sorted(pairs, key=lambda p: (p["confidence"] != "definite", p["a"]["name_key"])):
                a, b = p["a"], p["b"]
                ws.append([
                    "قطعی" if p["confidence"] == "definite" else "مشکوک", p["reason"],
                    a["pk"], a["code"], _source(a["code"]), a["name_fa"],
                    b["pk"], b["code"], _source(b["code"]), b["name_fa"],
                ])
            wb.save(xlsx)
        queued = 0 if dry_run else crm_merge.queue_found(pairs)
        self.stdout.write(
            f"pairs={len(pairs)} definite={definite} suspect={len(pairs) - definite} "
            f"queued={queued} crowded_keys_skipped={crowded}"
        )
