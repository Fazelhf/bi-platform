#!/usr/bin/env bash
# One-command update for the cPanel Python host.
#   bash ~/bi-platform/deploy.sh
# Pulls latest code, installs any new deps, migrates, collects static, and
# restarts the Passenger app. Safe to run repeatedly.
set -e

# --- host-specific: virtualenv activate path (edit if your host differs) ---
VENV="/home/ntpbiir/virtualenv/bi-platform/backend/3.12/bin/activate"
APP_DIR="$HOME/bi-platform"

cd "$APP_DIR"
echo "▸ گرفتن آخرین کد از گیت‌هاب…"
git pull

# shellcheck disable=SC1090
source "$VENV"
cd "$APP_DIR/backend"

echo "▸ نصب/به‌روزرسانی وابستگی‌ها…"
pip install -r requirements.txt -q

echo "▸ اعمال مایگریشن‌ها…"
python manage.py migrate --noinput

# One-time data loads. Both are no-ops once their dataset exists, which is
# what makes them safe here: the underlying commands can wipe and reload, and
# a deploy that did that every time would delete whatever the sales team had
# entered since the last one.
echo "▸ بارگذاری داده‌ی CRM (فقط بار اول)…"
python manage.py import_didar_crm --if-empty
python manage.py seed_crm --if-empty

# The accounting side. Unlike the دیدار load these have no --if-empty guard
# and do not need one: both are idempotent by key, a second run creates
# nothing, and neither touches a party that is waiting on the review queue.
# Running them every deploy is what picks up a fresher export — and picks up
# the invoices that a reviewer's decision has just made importable.
#
# Parties first: an invoice whose طرف‌حساب is not in the CRM is skipped and
# counted, so the wrong order silently imports nothing.
#
# Both print and return cleanly when data/arpa is empty, which matters under
# `set -e` — the workbooks are uploaded by hand and may not be there yet.
echo "▸ بارگذاری داده‌ی حسابداری آرپا…"
python manage.py import_arpa_parties --dir data/arpa
python manage.py import_arpa_invoices --dir data/arpa

# --approve, because these workbooks are the finished monthly report, not a
# draft someone is still editing: they are committed to the repository by the
# person who owns the figures. Left as drafts they import fine and then show
# nothing — the dashboard reads approved rows only, so the month lands in the
# database and stays invisible, which looks exactly like a failed import.
#echo "▸ بارگذاری کارنامه‌های تولید (فقط ماه‌های جدید)…"
#python manage.py import_production_excel --dir data/production --if-empty --approve

echo "▸ جمع‌آوری فایل‌های استاتیک…"
python manage.py collectstatic --noinput

echo "▸ ری‌استارت اپ…"
mkdir -p tmp && touch tmp/restart.txt

echo ""
echo "✅ به‌روزرسانی انجام شد. چند ثانیه صبر کنید و سایت را رفرش کنید:"
echo "   https://ntpbi.ir"
