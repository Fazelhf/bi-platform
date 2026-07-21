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
# Seed static dimensions + demo users + editable formulas (idempotent).
python manage.py seed_sales || true
python manage.py seed_production || true
python manage.py seed_users || true
python manage.py seed_formulas || true

exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
