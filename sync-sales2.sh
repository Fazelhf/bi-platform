#!/usr/bin/env bash
# Fill فروش ۲ from what CRM already holds: آرپا invoices and returns become
# issued documents (with a حواله and a «تسویه در آرپا» receipt), everything
# before the cut-over day becomes each customer's opening balance, and open
# CRM deals become draft proformas.
#
#   bash ~/bi-platform/sync-sales2.sh                    # from 1405/01/01
#   bash ~/bi-platform/sync-sales2.sh --from 1405/04/01  # another cut-over day
#   bash ~/bi-platform/sync-sales2.sh --dry-run          # report, write nothing
#   bash ~/bi-platform/sync-sales2.sh --undo             # take it all back out
#
# If fresh آرپا exports sit in backend/data/arpa, CRM is refreshed from them
# first; otherwise the invoices CRM already has are used as they are.
#
# Separate from deploy.sh for the same reason as import-data.sh: loading
# accounting data is a decision, not a side effect of shipping code.
#
# Re-running is safe and is how فروش ۲ stays current: every brought document
# carries `arpa:<code>`, so a second run adds only invoices that are new since
# the last one (or whose customer has since been matched in CRM).
set -e

VENV="/home/ntpbiir/virtualenv/bi-platform/backend/3.12/bin/activate"
APP_DIR="$HOME/bi-platform"
ARPA_DIR="data/arpa"

FROM="1405/01/01"
DRY_RUN=""
UNDO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from)    FROM="$2"; shift 2 ;;
    --from=*)  FROM="${1#--from=}"; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --undo)    UNDO=1; shift ;;
    *) echo "❌ گزینه‌ی ناشناخته: $1"; exit 1 ;;
  esac
done

# shellcheck disable=SC1090
source "$VENV"
cd "$APP_DIR/backend"

count_rows() {
  python manage.py shell -c "
from apps.crm.models import Customer, SalesInvoice
from apps.sales2.models import Receipt, SalesDocument
print('    CRM: مشتری', Customer.objects.count(), '  فاکتور آرپا', SalesInvoice.objects.count())
print('    فروش ۲: سند', SalesDocument.objects.count(), '  دریافت', Receipt.objects.count())
"
}

if [ -n "$UNDO" ]; then
  echo "▸ برداشتن هر چه از CRM به فروش ۲ آمده بود…"
  python manage.py sales2_cutover --undo
  count_rows
  exit 0
fi

echo "▸ قبل:"
count_rows
echo ""

# --- 1. CRM from the آرپا exports, when there are any -----------------------
if ls "$ARPA_DIR"/*.xlsx >/dev/null 2>&1; then
  CHECK=""
  [ -n "$DRY_RUN" ] && CHECK="--check"
  echo "▸ خروجی آرپا پیدا شد؛ به‌روزرسانی CRM…"
  python manage.py import_arpa_parties  --dir "$ARPA_DIR" $CHECK
  python manage.py import_arpa_invoices --dir "$ARPA_DIR" $CHECK
else
  echo "▸ خروجی آرپا در backend/$ARPA_DIR نیست؛ فاکتورهای فعلی CRM به کار می‌روند."
fi
echo ""

# --- 2. CRM into فروش ۲ ------------------------------------------------------
echo "▸ انتقال به فروش ۲ از $FROM…"
if [ -n "$DRY_RUN" ]; then
  python manage.py sales2_cutover --from "$FROM" --dry-run
  echo ""
  echo "✅ فقط گزارش — چیزی نوشته نشد. بدون --dry-run دوباره بزنید."
  exit 0
fi
python manage.py sales2_cutover --from "$FROM"

echo ""
echo "▸ بعد:"
count_rows
echo ""
echo "✅ فروش ۲ پر شد. فاکتورهای بی‌مشتری را در /crm/match-review وصل کنید و دوباره بزنید."
echo "   https://ntpbi.ir/sales2"
