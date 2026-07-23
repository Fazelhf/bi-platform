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

echo "▸ جمع‌آوری فایل‌های استاتیک…"
python manage.py collectstatic --noinput

echo "▸ ری‌استارت اپ…"
mkdir -p tmp && touch tmp/restart.txt

echo ""
echo "✅ به‌روزرسانی انجام شد. چند ثانیه صبر کنید و سایت را رفرش کنید:"
echo "   https://ntpbi.ir"
