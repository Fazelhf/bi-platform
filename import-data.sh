#!/usr/bin/env bash
# Load the Commercial Report workbook into the database.
#   bash ~/bi-platform/import-data.sh                  # find the file, import it
#   bash ~/bi-platform/import-data.sh FILE.xlsx        # name it explicitly
#   bash ~/bi-platform/import-data.sh --dry-run        # read it, write nothing
#   bash ~/bi-platform/import-data.sh --replace        # wipe first, then import
#
# Separate from deploy.sh on purpose. deploy.sh ships *code* and is safe to run
# any time; this ships one department's *operational file*, which is a decision
# someone makes — and running it on every deploy would re-read a workbook that
# may have been superseded, at a moment nobody chose.
#
# Re-running is safe: the importer matches پرونده‌ها by PI number and updates
# them in place, so a second run corrects rows rather than duplicating them.
set -e

VENV="/home/ntpbiir/virtualenv/bi-platform/backend/3.12/bin/activate"
APP_DIR="$HOME/bi-platform"

cd "$APP_DIR"

# Anything starting with "-" is a flag for the importer, not a filename.
FILE=""
FLAGS=()
for arg in "$@"; do
  case "$arg" in
    -*) FLAGS+=("$arg") ;;
    *)  FILE="$arg" ;;
  esac
done

# --- find the workbook ----------------------------------------------------
# Newest match wins: the file is re-sent as the month progresses, and the one
# uploaded last is the one meant to be loaded.
if [ -z "$FILE" ]; then
  FILE=$(ls -1t \
    "$APP_DIR"/*.xlsx \
    "$APP_DIR"/data/*.xlsx \
    "$HOME"/*.xlsx \
    2>/dev/null | head -1 || true)
fi

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  echo "❌ فایل اکسل پیدا نشد."
  echo ""
  echo "   جاهایی که گشتم:"
  echo "     $APP_DIR/*.xlsx"
  echo "     $APP_DIR/data/*.xlsx"
  echo "     $HOME/*.xlsx"
  echo ""
  echo "   فایل را در یکی از این مسیرها بگذارید، یا مسیرش را بدهید:"
  echo "     bash ~/bi-platform/import-data.sh /path/to/Commercial\\ Report.xlsx"
  exit 1
fi

echo "▸ فایل: $FILE"
echo "  (آخرین تغییر: $(date -r "$FILE" '+%Y-%m-%d %H:%M' 2>/dev/null || echo '؟'))"
echo ""

# shellcheck disable=SC1090
source "$VENV"
cd "$APP_DIR/backend"

# Through manage.py rather than a bare python heredoc: it is the only way that
# picks up the project's settings, whatever the host's working directory is.
count_rows() {
  python manage.py shell -c "
from apps.commercial.models import ForeignOrder, Shipment, Supplier
print('    پرونده‌ها:', ForeignOrder.objects.count(),
      '  محموله‌ها:', Shipment.objects.count(),
      '  تامین‌کننده‌ها:', Supplier.objects.count())
"
}

echo "▸ قبل از ایمپورت:"
count_rows

echo ""
echo "▸ خواندن فایل…"
python manage.py import_commercial_report "$FILE" "${FLAGS[@]}"

# A dry run wrote nothing, so a second count would only be confusing.
case " ${FLAGS[*]} " in
  *" --dry-run "*)
    echo ""
    echo "✅ فقط خوانده شد — چیزی در دیتابیس نوشته نشد."
    echo "   برای نوشتن، همین دستور را بدون --dry-run اجرا کنید."
    exit 0
    ;;
esac

echo ""
echo "▸ بعد از ایمپورت:"
count_rows

echo ""
echo "✅ دیتا وارد شد. سایت را رفرش کنید:"
echo "   https://ntpbi.ir/commercial/foreign"
