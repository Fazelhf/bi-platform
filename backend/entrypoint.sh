#!/usr/bin/env bash
set -e

echo "Waiting for database…"
python - <<'PY'
import os, time
import psycopg
url = os.environ.get("DATABASE_URL")
if url:
    for _ in range(30):
        try:
            psycopg.connect(url).close()
            break
        except Exception:
            time.sleep(1)
PY

python manage.py migrate --noinput
python manage.py collectstatic --noinput || true

# Seed static dimensions + editable formulas (idempotent).
python manage.py seed_sales || true
python manage.py seed_production || true
python manage.py seed_formulas || true

# On a FRESH database (no facts yet), load the real اردیبهشت ۱۴۰۵ data +
# users from the committed fixture so the deployed host is populated exactly
# like local. On an existing DB this is skipped (never clobbers live edits).
python - <<'PY'
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from apps.sales.models import FactSalesMonthly
from django.core.management import call_command
if not FactSalesMonthly.objects.exists():
    print("Fresh DB — loading seed_data.json fixture …")
    call_command("loaddata", "fixtures/seed_data.json")
else:
    print("DB already has data — skipping fixture load.")
PY

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
