/**
 * فروش ۲ API — پیش‌فاکتور، فاکتور، مرجوعی، حواله، دریافت و چک.
 *
 * Money comes back as strings so a Rial figure never rounds through a float
 * on its way to the screen.
 */
import api from "./client";

export type DocKind = "proforma" | "invoice" | "return";
export type DocStatus = "draft" | "issued" | "cancelled";
/** How far a proforma has been invoiced — counted from its invoices, never stored. */
export type InvoicingState = "open" | "partial" | "full" | "closed";
export type ReturnType = "goods" | "undelivered";

export interface CheckItem {
  code: string;
  level: "error" | "block" | "warn";
  message: string;
  line: number | null;
}

export interface DocLine {
  id?: number;
  source_line: number | null;
  product: number;
  product_code?: string;
  product_name: string;
  unit: string;
  /** 48 or 55 gsm for a roll; null for anything else. */
  grammage: number | null;
  description: string;
  quantity: string;
  unit_price_rial: string;
  discount_pct: string;
  gross_rial?: string;
  discount_rial?: string;
  net_rial?: string;
  vat_rial?: string;
  total_rial?: string;
  unit_cost_rial?: string;
  min_price_rial?: string;
  /** Issued proforma lines. */
  invoiced_qty?: string;
  remaining_qty?: string;
  /** Issued invoice lines (spec §2): D, R, X and what they allow. */
  delivered_qty?: string;
  returned_qty?: string;
  reduced_qty?: string;
  deliverable_qty?: string;
  returnable_qty?: string;
}

export interface DocSummary {
  id: number;
  kind: DocKind;
  kind_label: string;
  number: string;
  status: DocStatus;
  status_label: string;
  customer: number;
  display_customer: string;
  salesperson: number | null;
  salesperson_name: string;
  source: number | null;
  source_number: string;
  doc_date: string;
  valid_until: string | null;
  due_date: string | null;
  settlement: string;
  settlement_label: string;
  is_official: boolean;
  net_rial: string;
  vat_rial: string;
  total_rial: string;
  cost_rial: string;
  profit_rial: string;
  override_reason: string;
  is_expired: boolean;
}

export interface SalesDoc extends DocSummary {
  lines: DocLine[];
  channel: string;
  deal: number | null;
  warehouse: number | null;
  warehouse_name: string;
  vat_pct: string;
  subtotal_rial: string;
  discount_rial: string;
  note: string;
  issue_checks: CheckItem[];
  issued_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string;
  customer_name: string;
  customer_national_id: string;
  customer_economic_code: string;
  customer_address: string;
  customer_postal_code: string;
  customer_phone: string;
  derived: { id: number; kind: DocKind; kind_label: string; number: string; status: DocStatus; status_label: string }[];
  settlement_state: { allocated_rial: string; returned_rial: string; remaining_rial: string; is_settled: boolean } | null;
  delivery_state: "none" | "partial" | "full" | null;
  invoicing_state: InvoicingState | null;
  return_type: ReturnType;
  closed_at: string | null;
  close_reason: string;
  customer_info: {
    id: number; name_fa: string; national_id: string; economic_code: string;
    address: string; postal_code: string; phone: string;
  };
}

export interface Balance {
  invoiced_rial: string;
  returned_rial: string;
  paid_rial: string;
  balance_rial: string;
  cheques_pending_rial: string;
  exposure_rial: string;
  credit_limit_rial: string | null;
  available_rial: string | null;
  on_hold: boolean;
}

export interface CustomerRow {
  id: number;
  code: string;
  name_fa: string;
  national_id: string;
  economic_code: string;
  phone: string;
  city: string;
  province: string;
  owner: number | null;
  owner_name: string;
  address: string;
  postal_code: string;
  payment_terms: string;
  balance?: Balance;
}

export interface CustomerAccount {
  credit_limit_rial: string | null;
  credit_days: number;
  on_hold: boolean;
  note: string;
}

export interface CustomerDetail extends CustomerRow {
  balance: Balance;
  account: CustomerAccount;
  vat_cert_expires_at: string | null;
  documents: DocSummary[];
  receipts: Receipt[];
  open_invoices: { id: number; number: string; doc_date: string; due_date: string | null; total_rial: string; remaining_rial: string }[];
}

/** A price cell: the 200-roll list price, رسمی and غیر رسمی, for one grammage ("48" | "55" | "0"). */
export interface PriceCell { official: string | null; unofficial: string | null }

/** A price cell: the 200-roll list price, رسمی and غیر رسمی, for one grammage ("48" | "55" | "0"). */
export interface PriceCell { official: string | null; unofficial: string | null }

export interface ProductRow {
  id: number;
  code: string;
  name_fa: string;
  category: string;
  unit_label: string;
  is_sellable: boolean;
  min_price_rial: string;
  width_mm: number | null;
  length_m: number | null;
  is_printed: boolean;
  is_roll: boolean;
  prices: Record<string, PriceCell>;
  costs: Record<string, { cost_rial: string | null; month: number | null }>;
}

export interface DeliveryLine {
  id?: number;
  invoice_line: number;
  product_name?: string;
  unit?: string;
  invoiced_qty?: string;
  quantity: string;
}

export interface Delivery {
  id: number;
  number: string;
  status: "draft" | "issued" | "cancelled";
  status_label: string;
  invoice: number;
  invoice_number: string;
  customer_name: string;
  warehouse: number | null;
  warehouse_name: string;
  delivery_date: string;
  receiver_name: string;
  driver_name: string;
  driver_phone: string;
  vehicle_plate: string;
  waybill_no: string;
  shipping_address: string;
  note: string;
  issued_at: string | null;
  cancel_reason: string;
  lines: DeliveryLine[];
}

export interface Receipt {
  id: number;
  number: string;
  status: "issued" | "cancelled";
  status_label: string;
  customer: number;
  customer_name: string;
  received_on: string;
  method: "cash" | "transfer" | "pos" | "cheque";
  method_label: string;
  amount_rial: string;
  bank_account: number | null;
  bank_account_label: string;
  reference_no: string;
  cheque_no: string;
  sayad_no: string;
  cheque_bank: string;
  cheque_due_date: string | null;
  cheque_drawer: string;
  cheque_status: string;
  cheque_status_label: string;
  /** Finance confirms the money arrived; until then the receipt pays nothing. */
  finance_status: "pending" | "confirmed" | "rejected";
  finance_status_label: string;
  finance_note: string;
  finance_at: string | null;
  /** ثبت در سامانه صیاد. */
  sayad_registered: boolean;
  sayad_registered_at: string | null;
  /** When an unregistered cheque stops counting; null once registered. */
  sayad_deadline: string | null;
  /** Unregistered past its 48 hours: it no longer counts as paid. */
  is_lapsed: boolean;
  note: string;
  cancel_reason: string;
  allocations: { id: number; invoice: number; invoice_number: string; invoice_total_rial: string; amount_rial: string }[];
  unallocated_rial: string;
  counts_as_paid: boolean;
}

export interface Options {
  settings: { vat_pct: string; proforma_valid_days: number; default_warehouse: number | null; credit_policy: string };
  warehouses: Warehouse[];
  salespeople: { id: number; name: string }[];
  bank_accounts: { id: number; label: string; kind: string }[];
  channels: { value: string; label: string }[];
  settlements: { value: string; label: string }[];
  receipt_methods: { value: string; label: string }[];
  cheque_statuses: { value: string; label: string }[];
}

export interface Warehouse {
  id: number;
  code: string;
  name_fa: string;
  address: string;
  is_active: boolean;
}

export interface Settings {
  company_name: string;
  economic_code: string;
  national_id: string;
  registration_no: string;
  address: string;
  postal_code: string;
  phone: string;
  vat_pct: string;
  proforma_valid_days: number;
  credit_policy: "block" | "warn" | "off";
  print_terms: string;
  default_warehouse: number | null;
}

export interface Summary {
  month: { jalali_year: number; jalali_month: number };
  month_invoiced_rial: string;
  month_invoice_count: number;
  month_profit_rial: string;
  month_returns_rial: string;
  month_received_rial: string;
  receivable_rial: string;
  overdue_rial: string;
  cheques_pending_rial: string;
  cheques_due_week: Receipt[];
  open_proformas: number;
  drafts: number;
  loss_overrides: number;
  undelivered_invoices: number;
  top_customers: { customer: number; name: string; net_rial: string }[];
}

export interface SalesListRow {
  doc_id: number;
  kind: DocKind;
  kind_label: string;
  number: string;
  doc_date: string;
  customer: string;
  salesperson: string;
  product: string;
  unit: string;
  quantity: string;
  unit_price_rial: string;
  discount_rial: string;
  net_rial: string;
  vat_rial: string;
  total_rial: string;
  cost_rial: string;
  profit_rial: string;
}

export interface ReceivableRow {
  customer: number;
  name: string;
  due_rial: string;
  cash_rial: string;
  cheque_registered_rial: string;
  cheque_unregistered_rial: string;
  pending_finance_rial: string;
  unpaid_rial: string;
  unregistered_deadline: string | null;
}

export interface PriceSheetRow {
  id?: number;
  width_mm: number;
  length_m: number;
  cut_fee_rial: string;
  print_fee_rial: string;
  waste_pct: string | null;
  note: string;
}

export interface QtyTier { min_qty: number; pct: number }

export interface PriceSheet {
  id: number;
  name: string;
  grammage: 48 | 55;
  grammage_label: string;
  is_official: boolean;
  base_fi_rial: string;
  waste_pct: string;
  qty_tiers: QtyTier[];
  jalali_year: number;
  jalali_month: number;
  /** False: carried from an earlier month; copy it to edit this month's list. */
  is_own_month?: boolean;
  rows: PriceSheetRow[];
  prices: Record<number, Record<string, string>>;
}

export interface Quote {
  price_rial: string | null;
  cost_rial: string | null;
  source: string;
  is_roll: boolean;
  last_sale: { unit_price_rial: string; discount_pct: string; doc_date: string; number: string } | null;
}

export interface CostRow {
  product: number;
  name: string;
  is_roll: boolean;
  /** Per grammage ("48" | "55" | "0"): the cost in force and the month (YYYYMM) it was set in. */
  costs: Record<string, { cost_rial: string | null; month: number | null; source: string }>;
}

export interface CostImportRow {
  product: number;
  name: string;
  grammage: number;
  previous_rial: string | null;
  previous_month: number | null;
  cost_rial: string | null;
  status: "changed" | "new" | "kept" | "same";
  where: string;
}

export interface CostImportResult {
  jalali_year: number;
  jalali_month: number;
  rows: CostImportRow[];
  counts: Record<"changed" | "new" | "kept" | "same", number>;
  unknown: { name: string; where: string }[];
  written?: number;
  products_created?: number;
}

export interface CommissionLine {
  line: number;
  doc_id: number;
  kind: DocKind;
  number: string;
  doc_date: string;
  salesperson_id: number | null;
  salesperson: string;
  customer_id: number;
  customer: string;
  product: string;
  grammage: number | null;
  quantity: string;
  unit_price_rial: string;
  net_rial: string;
  total_rial: string;
  cost_unit_rial: string;
  cost_rial: string;
  margin_pct: string | null;
  rate_pct: string;
  rate_source: "tier" | "override" | "no_cost";
  override_reason: string;
  paid_share_pct: string;
  commission_paid_rial: string;
  commission_net_rial: string;
  commission_pending_rial: string;
}

export interface CommissionPerson {
  salesperson_id: number | null;
  salesperson: string;
  sales_rial: string;
  invoice_count: number;
  active_customers: number;
  new_customers: number;
  profit_rial: string;
  target_rial: string | null;
  target_pct: string | null;
  commission_paid_rial: string;
  commission_net_rial: string;
  commission_pending_rial: string;
  no_cost_lines: number;
  override_lines: number;
}

export interface CommissionTier { min_margin_pct: string; rate_pct: string }

export interface CommissionSheet {
  jalali_year: number;
  jalali_month: number;
  status: "open" | "approved";
  approved_at: string | null;
  approved_by: string;
  rows: CommissionLine[];
  people: CommissionPerson[];
  tiers: CommissionTier[];
}

export interface StatementEntry {
  date: string;
  type: string;
  label: string;
  ref_id: number;
  debit: string;
  credit: string;
  balance: string;
}

type Params = Record<string, string | number | boolean | undefined | null>;

function clean(p: Params = {}): Params {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== "" && v !== undefined && v !== null));
}

/** DRF pages everything; the screens here want the plain list. */
function rows<T>(data: T[] | { results: T[] }): T[] {
  return Array.isArray(data) ? data : data.results;
}

const B = "/sales2";

export const sales2Api = {
  options: () => api.get<Options>(`${B}/options/`).then((r) => r.data),
  summary: () => api.get<Summary>(`${B}/summary/`).then((r) => r.data),
  settings: () => api.get<Settings>(`${B}/settings/`).then((r) => r.data),
  saveSettings: (data: Partial<Settings>) => api.put<Settings>(`${B}/settings/`, data).then((r) => r.data),

  warehouses: () => api.get<Warehouse[]>(`${B}/warehouses/`).then((r) => r.data),
  saveWarehouse: (data: Partial<Warehouse>, id?: number) =>
    (id ? api.put(`${B}/warehouses/${id}/`, data) : api.post(`${B}/warehouses/`, data)).then((r) => r.data),

  products: (p: Params = {}) =>
    api.get<{ jalali_year: number; jalali_month: number; rows: ProductRow[] }>(`${B}/products/`, { params: clean(p) }).then((r) => r.data),
  saveProfile: (id: number, data: Partial<ProductRow>) => api.put(`${B}/products/${id}/profile/`, data).then((r) => r.data),
  savePriceItem: (product: number, is_official: boolean, price_rial: string, year: number, month: number) =>
    api.put(`${B}/price-items/`, { product, is_official, price_rial, year, month }).then((r) => r.data),
  priceMonth: (year: number, month: number) =>
    api.get<{ jalali_year: number; jalali_month: number; sheets: PriceSheet[] }>(`${B}/price-sheets/month/`, { params: { year, month } }).then((r) => r.data),
  copyPriceMonth: (year: number, month: number) =>
    api.post<{ jalali_year: number; jalali_month: number; sheets: PriceSheet[] }>(`${B}/price-sheets/month/`, { year, month }).then((r) => r.data),
  importPrices: (file: File, year: number, month: number) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("year", String(year));
    fd.append("month", String(month));
    return api.post<{ sheets: { name: string; rows: number; base_fi_rial: string }[] }>(`${B}/price-sheets/import/`, fd).then((r) => r.data);
  },
  exportPrices: (year: number, month: number) =>
    api.get(`${B}/price-sheets/export/`, { params: { year, month }, responseType: "blob" }).then((r) => r.data as Blob),
  financeReceipts: (status = "pending") =>
    api.get<Receipt[]>(`${B}/finance/receipts/`, { params: { status } }).then((r) => r.data),
  reviewReceipt: (id: number, confirm: boolean, note = "") =>
    api.post<Receipt>(`${B}/finance/receipts/${id}/review/`, { confirm, note }).then((r) => r.data),

  customers: (p: Params = {}) => api.get<CustomerRow[]>(`${B}/customers/`, { params: clean(p) }).then((r) => r.data),
  customer: (id: number) => api.get<CustomerDetail>(`${B}/customers/${id}/`).then((r) => r.data),
  saveAccount: (id: number, data: Partial<CustomerAccount>) =>
    api.put<CustomerAccount>(`${B}/customers/${id}/account/`, data).then((r) => r.data),
  statement: (id: number) =>
    api.get<{ customer: string; entries: StatementEntry[]; balance: Balance }>(`${B}/customers/${id}/statement/`).then((r) => r.data),

  documents: (p: Params = {}) =>
    api.get(`${B}/documents/`, { params: { page_size: 500, ...clean(p) } }).then((r) => rows<DocSummary>(r.data)),
  document: (id: number) => api.get<SalesDoc>(`${B}/documents/${id}/`).then((r) => r.data),
  saveDocument: (data: Record<string, unknown>, id?: number) =>
    (id ? api.patch<SalesDoc>(`${B}/documents/${id}/`, data) : api.post<SalesDoc>(`${B}/documents/`, data)).then((r) => r.data),
  removeDocument: (id: number) => api.delete(`${B}/documents/${id}/`),
  check: (id: number) => api.post<{ checks: CheckItem[] }>(`${B}/documents/${id}/check/`).then((r) => r.data.checks),
  issue: (id: number, override_reason = "") =>
    api.post<SalesDoc>(`${B}/documents/${id}/issue/`, { override_reason }).then((r) => r.data),
  cancel: (id: number, reason: string) =>
    api.post<SalesDoc>(`${B}/documents/${id}/cancel/`, { reason }).then((r) => r.data),
  convert: (id: number) => api.post<SalesDoc>(`${B}/documents/${id}/convert/`).then((r) => r.data),
  makeReturn: (id: number, type: ReturnType = "goods") =>
    api.post<SalesDoc>(`${B}/documents/${id}/make-return/`, { type }).then((r) => r.data),
  closeProforma: (id: number, reason: string) =>
    api.post<SalesDoc>(`${B}/documents/${id}/close/`, { reason }).then((r) => r.data),
  duplicate: (id: number, kind?: DocKind) =>
    api.post<SalesDoc>(`${B}/documents/${id}/duplicate/`, { kind }).then((r) => r.data),
  printData: (id: number) =>
    api.get<{ document: SalesDoc; company: Settings }>(`${B}/documents/${id}/print/`).then((r) => r.data),

  deliveries: (p: Params = {}) =>
    api.get(`${B}/deliveries/`, { params: { page_size: 500, ...clean(p) } }).then((r) => rows<Delivery>(r.data)),
  saveDelivery: (data: Record<string, unknown>, id?: number) =>
    (id ? api.patch<Delivery>(`${B}/deliveries/${id}/`, data) : api.post<Delivery>(`${B}/deliveries/`, data)).then((r) => r.data),
  removeDelivery: (id: number) => api.delete(`${B}/deliveries/${id}/`),
  issueDelivery: (id: number, override_reason = "") =>
    api.post<Delivery>(`${B}/deliveries/${id}/issue/`, { override_reason }).then((r) => r.data),
  cancelDelivery: (id: number, reason: string) =>
    api.post<Delivery>(`${B}/deliveries/${id}/cancel/`, { reason }).then((r) => r.data),

  receipts: (p: Params = {}) =>
    api.get(`${B}/receipts/`, { params: { page_size: 500, ...clean(p) } }).then((r) => rows<Receipt>(r.data)),
  saveReceipt: (data: Record<string, unknown>, id?: number) =>
    (id ? api.patch<Receipt>(`${B}/receipts/${id}/`, data) : api.post<Receipt>(`${B}/receipts/`, data)).then((r) => r.data),
  allocate: (id: number, allocations: "auto" | { invoice: number; amount_rial: string }[]) =>
    api.post<Receipt>(`${B}/receipts/${id}/allocate/`, { allocations }).then((r) => r.data),
  receivables: (p: Params = {}) =>
    api.get<{ rows: ReceivableRow[]; totals: Record<string, string>; grace_hours: number }>(
      `${B}/receivables/`, { params: clean(p) }).then((r) => r.data),
  sayad: (id: number, registered: boolean) =>
    api.post<Receipt>(`${B}/receipts/${id}/sayad/`, { registered }).then((r) => r.data),
  quote: (p: { product: number; grammage?: number | null; official?: boolean; quantity?: string | number; customer?: number | null; date?: string }) =>
    api.get<Quote>(`${B}/quote/`, { params: clean({ ...p, official: p.official === false ? "0" : "1" }) }).then((r) => r.data),
  savePriceSheet: (id: number, data: Partial<PriceSheet>) =>
    api.patch<PriceSheet>(`${B}/price-sheets/${id}/`, data).then((r) => r.data),
  costs: (p: Params = {}) =>
    api.get<{ jalali_year: number; jalali_month: number; rows: CostRow[] }>(`${B}/accounting-costs/`, { params: clean(p) }).then((r) => r.data),
  saveCost: (product: number, grammage: number, cost_rial: string, year: number, month: number) =>
    api.put(`${B}/accounting-costs/`, { product, grammage, cost_rial, year, month }).then((r) => r.data),
  importCosts: (file: File, year: number, month: number, confirm = false, createMissing = false) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("year", String(year));
    fd.append("month", String(month));
    if (confirm) fd.append("confirm", "1");
    if (createMissing) fd.append("create_missing", "1");
    return api.post<CostImportResult>(`${B}/accounting-costs/import/`, fd).then((r) => r.data);
  },
  commission: (year?: number, month?: number) =>
    api.get<CommissionSheet>(`${B}/commission/`, { params: clean({ year, month }) }).then((r) => r.data),
  approveCommission: (year: number, month: number, reopen = false) =>
    api.post<CommissionSheet>(`${B}/commission/approve/`, { year, month, reopen }).then((r) => r.data),
  overrideCommission: (line: number, rate_pct: string | null, reason: string) =>
    api.post<CommissionSheet>(`${B}/commission/override/`, { line, rate_pct, reason }).then((r) => r.data),
  saveTiers: (tiers: CommissionTier[]) =>
    api.put<CommissionTier[]>(`${B}/commission/tiers/`, { tiers }).then((r) => r.data),
  exportCommission: (year: number, month: number) =>
    api.get(`${B}/commission/export/`, { params: { year, month }, responseType: "blob" }).then((r) => r.data as Blob),
  chequeStatus: (id: number, cheque_status: string) =>
    api.post<Receipt>(`${B}/receipts/${id}/cheque-status/`, { cheque_status }).then((r) => r.data),
  cancelReceipt: (id: number, reason: string) =>
    api.post<Receipt>(`${B}/receipts/${id}/cancel/`, { reason }).then((r) => r.data),

  salesList: (p: Params = {}) =>
    api.get<{ rows: SalesListRow[]; totals: Record<string, string>; by_salesperson: { name: string; net_rial: string }[] }>(
      `${B}/sales-list/`, { params: clean(p) }).then((r) => r.data),
  exportSalesList: (p: Params = {}) =>
    api.get(`${B}/sales-list/export/`, { params: clean(p), responseType: "blob" }).then((r) => r.data as Blob),
};
