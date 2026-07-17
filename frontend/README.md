# BI Platform — Frontend (Phase 1b: Sales)

Vue 3 + TypeScript + Vite + Pinia SPA. RTL, Persian-first. Two experiences:

- **داشبورد مدیریتی** (`/dashboard`) — the executive/Power-BI view: KPI cards +
  ECharts (team revenue, province sales-vs-target) + salesperson leaderboard.
- **ورود اطلاعات** (`/entry`) — the Excel-like operator view: an AG Grid where
  each salesperson is a row and the 8 measures are editable cells. Edits save
  instantly and reset the row to *draft*; managers submit/approve inline.

## Stack

Vue 3 · TypeScript · Vite 6 · Pinia · Vue Router · TailwindCSS ·
Apache ECharts · AG Grid (Community) · Axios (JWT + refresh interceptor).

> **Grid note:** the master spec prefers *AG Grid Enterprise*. This uses AG Grid
> **Community** to stay license-free; swapping in Enterprise (range selection,
> Excel export, master/detail) is a drop-in dependency + license-key change.

## Run

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173  (proxies /api -> 127.0.0.1:8000)
```

The backend must be running on `:8000` (see `../backend/README.md`). Log in with
the executive user you created there.

## Structure

```
src/
  api/            axios client (JWT refresh) + sales endpoints
  stores/auth.ts  Pinia auth store
  router/         routes + auth guard
  composables/    useChart (ECharts lifecycle wrapper)
  components/     AppLayout, KpiCard, BarChart
  views/          LoginView, DashboardView, DataEntryView
  utils/format.ts Rial / percent / Persian-numeral formatting
```
