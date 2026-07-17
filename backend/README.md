# BI Platform — Backend (Phase 1a: Sales)

Django 5 + DRF backend implementing the **Sales** domain as a dimensional
(star-schema) data warehouse, with an Excel importer, a KPI computation
engine, JWT auth + RBAC, and a Swagger-documented API.

## What's here

```
config/            Django project (settings, urls, celery, wsgi/asgi)
apps/core/         DimPeriod (Jalali month grain), DimKPI catalog, base model
apps/accounts/     Custom User with RBAC roles (executive/manager/operator/viewer)
apps/sales/        Star schema + API + KPI engine + importer
  models.py            Dims (Employee, Team, Province, Bank) + Facts
  services/kpi.py      KPI engine — replaces the workbook's hidden calc sheets
  management/commands/
    seed_sales.py          teams, 31 provinces, KPI catalog
    import_sales_excel.py  loads the همکار/Employee workbook
```

### Star schema

- **Dimensions:** `DimPeriod`, `DimEmployee`, `DimTeam`, `DimProvince`, `DimBank`, `DimKPI`
- **Facts:** `FactSalesMonthly` (employee × month, the 8 raw measures + approval
  workflow), `FactSalesProvince`, `FactCollection`, `FactKPI` (computed results
  at company / team / employee scope)

### KPIs computed (from Employee!Sheet3)

revenue · target achievement · share of sales volume · call-to-sale conversion ·
profit margin · cost-to-sales · average invoice value · new-customer ratio.
Ratios at team/company scope are computed from aggregated numerators — fixing an
averaging inconsistency in the original spreadsheet.

## Quick start (local, SQLite — zero config)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # or the dev subset
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_sales
.venv/Scripts/python manage.py import_sales_excel \
    --employee-file "KPI همکار اردیبهشت 1405 (1).xlsx" \
    --year 1405 --month 2 --approve
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

- API docs (Swagger): http://127.0.0.1:8000/api/docs/
- Get a token: `POST /api/auth/token/` `{username, password}`
- Executive dashboard payload: `GET /api/sales/dashboard/summary/?period=1`

Leave `DATABASE_URL` unset for SQLite; set it (see `.env.example`) for Postgres.

## Data-quality notes (from source analysis, not yet auto-cleaned)

- The Employee workbook has no data in the بانکی (Banking) team columns → that
  team shows 0 revenue.
- Bank collections live in the *Organizational* workbook, not the Employee one,
  so `FactCollection` is empty after importing only the Employee file.
- `ورودی!C15 = 68` sits in a Rial column and is almost certainly a typo; it is
  imported verbatim and should be reviewed.
