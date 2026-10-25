#!/usr/bin/env bash
# Safe one-command update for the cPanel Python host.
#
# Run it from the server like this — it reads the script from the commit being
# deployed, so a fix to the deploy itself is in effect on the very same run:
#
#   cd ~/bi-platform && git fetch origin && git show origin/main:deploy.sh > /tmp/bi-deploy.sh && bash /tmp/bi-deploy.sh
#
# Going back to an earlier version is the same command with the version (as
# the site shows it) or a commit after it, and coming back is the plain
# command again:
#
#   … && bash /tmp/bi-deploy.sh 1.50      # the site as it was before PR #51
#   … && bash /tmp/bi-deploy.sh 3f2a9c1   # any commit
#   … && bash /tmp/bi-deploy.sh           # back to the latest main
#
# An older version goes through every check below, exactly like a new one.
# Its migrations are not undone — that would drop the data the newer version
# stored — so the database stays ahead of the code; the run lists what the
# older code does not know about.
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
# A deploy never loads data: CRM's آرپا and دیدار data come in through the
# site's own upload pages, by the system admin.

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

# The stage and the live site share ONE virtualenv, so installing the new
# commit's requirements changes the packages under the live code too. The
# deploy of ۵ مهر ۱۴۰۵ failed at migrate (Django 5.2 against PostgreSQL 13)
# and left Django 5.2 installed under the old code: the site was one restart
# away from going down. Any failure after the install puts the live folder's
# own requirements back.
DEPS_CHANGED=""
restore_deps() {
  [ -n "$DEPS_CHANGED" ] || return 0
  echo "▸ برگرداندن وابستگی‌های نسخه‌ی فعلی سایت…"
  pip install -r "$APP_DIR/backend/requirements.txt" -q \
    || echo "⚠️ برگرداندن وابستگی‌ها ناموفق بود — این را دستی اجرا کنید: pip install -r $APP_DIR/backend/requirements.txt"
}

fail() {
  echo
  echo "❌ $*"
  restore_deps
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
git fetch origin "$BRANCH" --tags --quiet || { echo "❌ fetch ناموفق بود"; exit 1; }

# What to deploy: the latest main, or the version / commit given as $1.
# «1.N» is the site as it stood just before PR N+1 was merged: the first
# parent of the oldest merge of a later PR. A tag v1.N wins over that rule —
# it pins a version whose history the rule reads wrong (1.50: main was
# fast-forwarded onto the PR branch before its merge commit was made).
resolve_target() {
  local want="$1" n merge
  if [[ "$want" =~ ^1\.([0-9]+)$ ]]; then
    n="${BASH_REMATCH[1]}"
    if git rev-parse -q --verify "refs/tags/v$want^{commit}" >/dev/null; then
      git rev-parse "refs/tags/v$want^{commit}"; return
    fi
    merge=$(git log "origin/$BRANCH" --merges --reverse --format='%H %s' \
      | awk -v n="$n" 'match($0, /Merge pull request #[0-9]+/) {
          pr = substr($0, RSTART + 20, RLENGTH - 20) + 0
          if (pr > n) { print $1; exit } }')
    if [ -n "$merge" ]; then
      git rev-parse "$merge^1"
    else
      git rev-parse "origin/$BRANCH"   # 1.N is the latest version
    fi
  else
    git rev-parse -q --verify "$want^{commit}"
  fi
}

TARGET="${1:-}"
if [ -n "$TARGET" ]; then
  NEW=$(resolve_target "$TARGET") || NEW=""
  [ -n "$NEW" ] || { echo "❌ نسخه یا کامیت «$TARGET» پیدا نشد"; exit 1; }
  git merge-base --is-ancestor "$NEW" "origin/$BRANCH" \
    || { echo "❌ «$TARGET» روی $BRANCH نیست؛ فقط نسخه‌های مرج‌شده قابل دیپلوی‌اند"; exit 1; }
else
  NEW=$(git rev-parse "origin/$BRANCH")
fi
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
DEPS_CHANGED=1
pip install -r requirements.txt -q || fail "نصب وابستگی‌ها ناموفق بود"

say "آیا نسخه‌ی جدید روی همین پایتون راه می‌افتد؟"
python -c "import passenger_wsgi" || fail "نسخه‌ی جدید راه نمی‌افتد (خطای بالا را ببینید)"
python manage.py check || fail "manage.py check خطا داد"
# `check` never opens the database; this does — so a Django that cannot talk
# to this server's database is caught here, before anything is migrated.
python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('   دیتابیس:', connection.vendor, connection.pg_version if connection.vendor == 'postgresql' else '')" \
  || fail "نسخه‌ی جدید به دیتابیس سرور وصل نمی‌شود"

say "اعمال مایگریشن‌ها (فقط افزودنی‌اند؛ نسخه‌ی فعلی سایت با آن‌ها کار می‌کند)…"
python manage.py migrate --noinput || fail "مایگریشن ناموفق بود"

if [ -n "$TARGET" ]; then
  # An older version: the database may hold migrations this code has never
  # heard of. They stay (undoing them drops data), and they are named here so
  # a failure on the old version can be traced to them.
  python manage.py shell -c "
from django.db import connection
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(connection)
ahead = sorted(set(loader.applied_migrations) - set(loader.disk_migrations))
if ahead:
    print('   ⚠️ دیتابیس جلوتر از این نسخه است؛ این مایگریشن‌ها اعمال‌شده می‌مانند:')
    for app, name in ahead:
        print('     ', app, name)
"
fi

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
if [ -n "$TARGET" ]; then
  # Detached, so local main stays where it is and the plain command brings
  # the latest back.
  go_live() { git checkout --quiet --detach "$NEW"; }
else
  go_live() { git checkout --quiet "$BRANCH" && git merge --ff-only --quiet "origin/$BRANCH"; }
fi
if ! go_live; then
  git checkout --quiet --detach "$PREV" || true
  fail "جابه‌جایی کد سایت ناموفق بود"
fi

rollback() {
  echo
  echo "❌ $1"
  echo "▸ برگرداندن خودکار سایت به نسخه‌ی قبلی ($(git -C "$APP_DIR" log --oneline -1 "$PREV"))…"
  cd "$APP_DIR" && git checkout --quiet --detach "$PREV"
  restore_deps
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

# --- 3. no data loads ----------------------------------------------------------------------
# A deploy ships code and nothing else. CRM data comes in only through the
# site — «ورود از آرپا» and «ورود از دیدار» — when the system admin uploads an
# export. Loading data here used to undo deletes and hand edits made in the
# app on every release, on a schedule set by code changes.

echo
echo "✅ به‌روزرسانی انجام شد و سایت جواب می‌دهد: $SITE_URL"
echo "   نسخه: $(git -C "$APP_DIR" log --oneline -1)"
if [ -n "$TARGET" ]; then
  echo "   سایت روی نسخه‌ی «$TARGET» است. برای برگشت به آخرین نسخه همین دستور را بدون شماره اجرا کنید."
fi
