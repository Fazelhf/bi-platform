# Source-workbook analysis

Analysis of the three real KPI workbooks (period اردیبهشت ۱۴۰۵), which serve as
the functional spec for this platform. The company is a **paper-roll
manufacturer + nationwide distributor** with two reporting halves: commercial
(sales) and production (factory).

## 1. سازمانی / Organizational Sales KPI

- **Grain:** company-wide; columns = named salespeople + a SUM total.
- **8 entered measures** (rows 3–10): revenue (Rial), invoice count, active
  customers, new customers, profit, cost, target, calls.
- **Province block** (rows 14–48): sales + target for each of 31 provinces
  (Tehran broken out separately).
- **Reference lists:** Iranian banks + PSPs (payment gateways); two banks carry
  collection amounts → these are **dimensions**, not facts.

## 2. همکار / Employee KPI

- `ورودی` (Input): same 8 measures for **9 salespeople** — the finest-grain
  source, used by the importer.
- `Sheet3` (hidden): the real **calculation engine**. Derives KPIs and groups
  salespeople into **5 teams** — بانکی، ایران غرب، ایران شرق، تهران، بی‌تو‌بی.
- `داشبورد فروشنده` / `داشبورد تیم`: **empty** — the intended dashboards were
  never built. This platform fills that gap.

## 3. تولید / Production KPI  (Phase 2)

- Per-line input (برش ۱–۵ + printing): shifts, indexed output, waste %, repairs,
  three downtime reasons. Cost block + revenue block (roll counts × piece-rate).
- Fan-out to per-machine sheets → aggregate → **7 production KPIs** against
  actual / target / ideal with deviation and efficiency %:
  production productivity · waste rate · line-stoppage rate · labor productivity
  · defect-free rate · cost-per-roll · financial-return rate.

## Dimensional model (implemented for Sales)

**Dimensions:** `DimPeriod` (Jalali month), `DimEmployee`, `DimTeam`,
`DimProvince`, `DimBank`, `DimKPI`.
**Facts:** `FactSalesMonthly` (employee × month), `FactSalesProvince`,
`FactCollection`, `FactKPI` (computed, at company/team/employee scope).

## Sales KPI catalog (implemented)

| Code | Persian | Formula | Unit | Direction |
|------|---------|---------|------|-----------|
| `revenue` | فروش ریالی | Σ revenue | Rial | higher |
| `target_achievement` | درصد تحقق تارگت | revenue / target × 100 | % | higher |
| `volume_share` | سهم از حجم فروش | revenue / company revenue × 100 | % | higher |
| `call_conversion` | نرخ تبدیل تماس به فروش | invoices / calls × 100 | % | higher |
| `profit_margin` | حاشیه سود | profit / revenue × 100 | % | higher |
| `cost_to_sales` | نسبت هزینه به فروش | cost / revenue × 100 | % | lower |
| `avg_invoice_value` | میانگین ارزش فاکتور | revenue / invoices | Rial | higher |
| `new_customer_ratio` | نسبت مشتری جدید | new / active customers × 100 | % | higher |

At team/company scope, ratios are computed from **aggregated** numerators &
denominators (not averaged per-person ratios) — this corrects an inconsistency
in the source spreadsheet.

## Data-quality issues found (redesigned, not copied)

- `#REF!` errors in Employee!Sheet3 (R7, R26) and Production!KPI (R7).
- Hard-coded overrides on top of formulas (Sheet3 G26=45, H26=120).
- `ورودی!C15 = 68` in a Rial column — almost certainly a typo.
- Live divide-by-zero `*****` cells in several KPI outputs.
- Salesperson roster differs between the two sales files (5 vs 9) with no shared
  key → solved here by a single `DimEmployee` dimension.
