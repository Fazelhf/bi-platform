#!/usr/bin/env bash
# Safe one-command update for the cPanel Python host.
#
# Run it from the server like this — it reads the script from the commit being
# deployed, so a fix to the deploy itself is in effect on the very same run:
#
#   cd ~/bi-platform && git fetch origin && git show origin/main:deploy.sh > /tmp/bi-deploy.sh && bash /tmp/bi-deploy.sh
#
# Why it is shaped like this. The deploy of ۲۳ شهریور ۱۴۰۵ took the whole site
# down: `git pull` put new code under the live app, every request came back as
# LiteSpeed's «Internal Error», and the site stayed down until the code was
# rolled back by hand. Nothing in the old script noticed. So now:
#
#   1. The new commit is checked out in a SEPARATE folder and started there —
#      import, `manage.py check`, real requests — with the same Python, the
#      same .env and the same database. The live site is not touched.
#   2. Migrations run from that folder. They only add, so the old code still
#      serving the site keeps working while they apply.
#   3. Only then does the live folder move to the new commit and restart.
#   4. The live site has to answer. If it does not, the live folder goes back
#      to the previous commit on its own, restarts, and the log is printed.
#
# Data loads (CRM / آرپا) run last and can never block or undo a deploy: a
# failed import is reported, the site stays up.

set -uo pipefail

# --- host-specific ------------------------------------------------------------
VENV="/home/ntpbiir/virtualenv/bi-platform/backend/3.12/bin/activate"
APP_DIR="$HOME/bi-platform"
BRANCH="${BRANCH:-main}"
SITE_URL="${SITE_URL:-https://ntpbi.ir}"
# The host the in-folder test requests claim to be for. It has to be one
# ALLOWED_HOSTS accepts, so it is the live site's own.
SITE_HOST="${SITE_URL#*://}"
SITE_HOST="${SITE_HOST%%/*}"
STAGE="$HOME/.bi-deploy-stage"
LOG_FILE="$APP_DIR/backend/stderr.log"

say()  { echo; echo "▸ $*"; }

cleanup_stage() {
  cd "$APP_DIR" 2>/dev/null || return 0
  git worktree remove --force "$STAGE" >/dev/null 2>&1 || true
  git worktree prune >/dev/null 2>&1 || true
}

fail() {
  echo
  echo "❌ $*"
  echo "سایت دست نخورد و روی نسخه‌ی قبلی ماند."
  cleanup_stage
  exit 1
}

restart_app() {
  mkdir -p "$APP_DIR/backend/tmp" && touch "$APP_DIR/backend/tmp/restart.txt"
}

# The site is up when the SPA shell loads and the API answers the way Django
# answers — 401/403 without a token is healthy. A 5xx, a timeout or LiteSpeed's
# own error page is not. Up to a minute, because the first request after a
# restart has to start Python.
site_is_up() {
  local home api
  for _ in $(seq 1 12); do
    # curl prints 000 itself on a timeout; `|| true` only keeps a failed
    # connection from ending the loop.
    home=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$SITE_URL/?deploy-check=$RANDOM") || true
    api=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -H 'Accept: application/json' "$SITE_URL/api/executive/site-settings/") || true
    echo "   خانه: ${home:-000} · API: ${api:-000}"
    if [ "$home" = "200" ] && { [ "$api" = "200" ] || [ "$api" = "401" ] || [ "$api" = "403" ]; }; then
      return 0
    fi
    sleep 5
  done
  return 1
}

# --- 0. where we are ------------------------------------------------------------
cd "$APP_DIR" || { echo "❌ پوشه‌ی $APP_DIR پیدا نشد"; exit 1; }

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "❌ روی سرور فایل‌های ردیابی‌شده تغییر کرده‌اند؛ دیپلوی آن‌ها را پاک نمی‌کند:"
  git status --short --untracked-files=no
  echo "اول بررسی کنید (git diff) و سپس دوباره اجرا کنید."
  exit 1
fi

PREV=$(git rev-parse HEAD)
say "گرفتن آخرین کد از گیت‌هاب…"
git fetch origin "$BRANCH" --quiet || { echo "❌ fetch ناموفق بود"; exit 1; }
NEW=$(git rev-parse "origin/$BRANCH")
echo "   نسخه‌ی فعلی: $(git log --oneline -1 "$PREV")"
echo "   نسخه‌ی جدید:  $(git log --oneline -1 "$NEW")"

# shellcheck disable=SC1090
source "$VENV" || { echo "❌ virtualenv پیدا نشد: $VENV"; exit 1; }

# --- 1. prove the new commit in a separate folder -------------------------------------
say "آماده‌سازی نسخه‌ی جدید در پوشه‌ی جداگانه (سایت دست نمی‌خورد)…"
cleanup_stage
git worktree add --detach --quiet "$STAGE" "$NEW" || fail "ساخت پوشه‌ی آزمایشی ناموفق بود"
if [ -f "$APP_DIR/backend/.env" ]; then
  cp "$APP_DIR/backend/.env" "$STAGE/backend/.env"
fi
cd "$STAGE/backend" || fail "پوشه‌ی آزمایشی باز نشد"

say "نصب/به‌روزرسانی وابستگی‌ها…"
pip install -r requirements.txt -q || fail "نصب وابستگی‌ها ناموفق بود"

say "آیا نسخه‌ی جدید روی همین پایتون راه می‌افتد؟"
python -c "import passenger_wsgi" || fail "نسخه‌ی جدید راه نمی‌افتد (خطای بالا را ببینید)"
python manage.py check || fail "manage.py check خطا داد"

say "اعمال مایگریشن‌ها (فقط افزودنی‌اند؛ نسخه‌ی فعلی سایت با آن‌ها کار می‌کند)…"
python manage.py migrate --noinput || fail "مایگریشن ناموفق بود"

say "درخواست واقعی به نسخه‌ی جدید، روی دیتابیس واقعی…"
DEPLOY_HOST="$SITE_HOST" python manage.py shell -c "
import os, sys
from django.test import Client
host = os.environ['DEPLOY_HOST']
c = Client(raise_request_exception=True)
home = c.get('/', HTTP_HOST=host).status_code
api = c.get('/api/executive/site-settings/', HTTP_HOST=host, HTTP_ACCEPT='application/json').status_code
print('   خانه:', home, '· API:', api)
sys.exit(0 if home == 200 and api in (200, 401, 403) else 1)
" || fail "نسخه‌ی جدید به درخواست جواب درست نداد"

# --- 2. go live ----------------------------------------------------------------------------
say "انتقال سایت به نسخه‌ی جدید…"
cd "$APP_DIR" || fail "پوشه‌ی سایت باز نشد"
cleanup_stage
if ! { git checkout --quiet "$BRANCH" && git merge --ff-only --quiet "origin/$BRANCH"; }; then
  git checkout --quiet --detach "$PREV" || true
  fail "جابه‌جایی کد سایت ناموفق بود"
fi

rollback() {
  echo
  echo "❌ $1"
  echo "▸ برگرداندن خودکار سایت به نسخه‌ی قبلی ($(git -C "$APP_DIR" log --oneline -1 "$PREV"))…"
  cd "$APP_DIR" && git checkout --quiet --detach "$PREV"
  restart_app
  if site_is_up; then
    echo "✅ سایت روی نسخه‌ی قبلی برگشت و کار می‌کند."
  else
    echo "⚠️ سایت حتی روی نسخه‌ی قبلی هم جواب نمی‌دهد — مشکل از کد نیست (سرور/دیتابیس)."
  fi
  echo
  echo "▸ آخرین خطاهای لاگ ($LOG_FILE):"
  tail -60 "$LOG_FILE" 2>/dev/null || echo "   (فایل لاگ پیدا نشد)"
  echo
  echo "این خروجی را برای بررسی بفرستید. برای دیپلوی بعدی همین دستور را دوباره اجرا کنید."
  exit 1
}

cd "$APP_DIR/backend" || rollback "پوشه‌ی backend باز نشد"

say "جمع‌آوری فایل‌های استاتیک…"
python manage.py collectstatic --noinput -v 0 || rollback "collectstatic ناموفق بود"

say "ری‌استارت اپ…"
restart_app

say "بررسی سایت زنده…"
site_is_up || rollback "سایت بعد از ری‌استارت جواب نداد"

# --- 3. data loads: reported, never fatal ------------------------------------------------
# Both importers are idempotent by key and no-ops once their data exists; the
# workbooks are uploaded by hand and may not be there. A failure here says so
# and leaves the (already healthy) site alone.
say "بارگذاری داده‌ی CRM (فقط بار اول)…"
python manage.py import_didar_crm --if-empty || echo "⚠️ بارگذاری CRM خطا داد — سایت سالم است."

say "بارگذاری داده‌ی حسابداری آرپا…"
python manage.py import_arpa_parties --dir data/arpa || echo "⚠️ import_arpa_parties خطا داد — سایت سالم است."
python manage.py import_arpa_invoices --dir data/arpa || echo "⚠️ import_arpa_invoices خطا داد — سایت سالم است."

echo
echo "✅ به‌روزرسانی انجام شد و سایت جواب می‌دهد: $SITE_URL"
echo "   نسخه: $(git -C "$APP_DIR" log --oneline -1)"
