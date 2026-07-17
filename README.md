# Enterprise BI Platform

A centralized **Business Intelligence platform** (in the spirit of Power BI /
Tableau / Looker) for executive reporting, KPI management, and analytics —
replacing the company's manual Excel-based KPI workflow with a proper data
warehouse, an Excel-like data-entry experience for operators, and live
dashboards for executives.

Built from analysis of the company's real reporting workbooks (a paper-roll
manufacturer + nationwide distributor). See
[`docs/analysis.md`](docs/analysis.md) for the source-workbook analysis that
drives the design.

## Status — Phase 1 (Sales domain) ✅

| Layer | Status |
|-------|--------|
| **1a** Backend + data warehouse (Django/DRF, star schema, Excel importer, KPI engine, JWT/RBAC, Swagger) | ✅ built & verified on real data |
| **1b** Frontend (Vue 3 + TS + Pinia, AG Grid entry, ECharts dashboard, RTL/Persian) | ✅ built & verified in browser |
| **1c** Infra (Docker, Postgres, Redis, RabbitMQ, Celery, Nginx, GitHub Actions) | ✅ compose + CI |

**Next phases:** Production domain (7 manufacturing KPIs) · Employee scorecards ·
executive PDF/Excel export · 2FA · row-level security by team.

## Architecture

```
┌────────────┐   Excel import    ┌─────────────────────────────┐
│  Workbooks │ ────────────────► │  PostgreSQL data warehouse  │
└────────────┘                   │  (star schema: dims + facts)│
                                 └─────────────┬───────────────┘
   operators                                   │ KPI engine (Celery)
   ┌────────────┐   REST/JWT      ┌─────────────▼───────────────┐
   │  AG Grid   │ ◄─────────────► │  Django + DRF API + Swagger │
   │  entry     │                 └─────────────┬───────────────┘
   └────────────┘                               │
   executives                                   │
   ┌────────────┐   REST/JWT                     │
   │  ECharts   │ ◄─────────────────────────────┘
   │  dashboard │
   └────────────┘
```

- **Operators** enter data in an Excel-like grid → **managers** approve →
  **executives** see live dashboards. Approved data is the single source of truth.
- KPIs are computed in the pipeline (`apps/sales/services/kpi.py`), not in the
  grid — the workbook's hidden calc sheets become `FactKPI` rows.

## Run locally (two terminals, zero Docker)

```bash
# 1) Backend  (SQLite, no config)
cd backend && python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_sales
.venv/Scripts/python manage.py import_sales_excel \
    --employee-file "path/to/KPI همکار اردیبهشت 1405.xlsx" --year 1405 --month 2 --approve
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver          # :8000, docs at /api/docs/

# 2) Frontend
cd frontend && npm install && npm run dev          # :5173
```

## Run with Docker (full stack)

```bash
cp .env.example .env          # then edit SECRET_KEY etc.
docker compose up --build
# Frontend + API behind Nginx:  http://localhost:8080
# RabbitMQ management UI:       http://localhost:15672
```

## Repository layout

```
backend/    Django 5 + DRF — warehouse, KPI engine, importer, API   (see backend/README.md)
frontend/   Vue 3 + TS + Vite — dashboard + Excel-like entry         (see frontend/README.md)
docs/       Source-workbook analysis + KPI catalog
docker-compose.yml   Postgres · Redis · RabbitMQ · backend · worker · frontend/Nginx
.github/    CI (backend checks/tests + frontend build)
```
