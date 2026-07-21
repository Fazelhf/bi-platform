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

## Status

### Phase 1 — Sales domain ✅
| Layer | Status |
|-------|--------|
| **1a** Backend + warehouse (star schema, Excel importer, KPI engine, JWT/RBAC, Swagger) | ✅ verified on real data |
| **1b** Frontend (Vue 3 + TS + Pinia, AG Grid entry, ECharts dashboard, RTL/Persian) | ✅ verified in browser |
| **1c** Infra (Docker, Postgres, Redis, RabbitMQ, Celery, Nginx, GitHub Actions) | ✅ compose + CI |

### Phase 2 — Production domain + unification ✅
| Layer | Status |
|-------|--------|
| **2a** Unified KPI core — `FactKPI` moved to `core`, conformed scopes (company/team/employee/machine/product) shared by every domain | ✅ verified |
| **2b** Production warehouse + KPI engine (7 factory KPIs, machines/products/costs, importer) — fixes the workbook's `#REF!`/`#DIV/0!`/unclosed-paren defects | ✅ verified on real data |
| **2c** Unified executive overview — sales + production on one screen, one API, one period | ✅ verified in browser |

### Phase 3 — Sales channels + two-role access ✅
| Layer | Status |
|-------|--------|
| **3a** Sales split into two channels (team/همکار + organizational/سازمانی); organizational importer adds key-account reps, provincial sales & bank collections — total company sales now **188.2B** | ✅ verified on real data |
| **3b** Two-role access model — CEO (executive, read-only, all dashboards) vs department managers (each edits only their section/channel), `/api/auth/me/`, 5 permission tests | ✅ verified via API + tests |
| **3c** Role-aware frontend — CEO's 4-section view (کلی/تولید/فروش همکار/فروش کلی); managers land on their own entry only; department-guarded routes | ✅ verified in browser |

**Personas (demo, password `demo12345`):** `ceo` (executive) · `prod_manager` ·
`org_manager` · `team_manager` · `admin` (Django superuser).

**Next candidates:** multi-month trends & month-over-month comparison · executive
PDF/Excel export · 2FA · scheduled KPI recompute via Celery · row-level detail
security within a channel.

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
.venv/Scripts/python manage.py seed_production
.venv/Scripts/python manage.py seed_users          # CEO + 3 managers + admin
.venv/Scripts/python manage.py import_sales_excel \
    --employee-file "path/to/KPI همکار اردیبهشت 1405.xlsx" --year 1405 --month 2 --approve
.venv/Scripts/python manage.py import_org_sales_excel \
    --file "path/to/سازمانیKPI ورودی اردیبهشت 1405.xlsx" --year 1405 --month 2 --approve
.venv/Scripts/python manage.py import_production_excel \
    --file "path/to/KPI اردیبهشت تولید1405.xlsx" --year 1405 --month 2 --approve
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
