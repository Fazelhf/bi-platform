import api from "./client";

/**
 * CRM API surface.
 *
 * The important type here is `Drill`: every aggregate row a report returns
 * carries one, and it is literally the query that reproduces the records
 * behind that number. The UI never reconstructs a filter by hand — it just
 * posts the drill back, which is why a drawer can never disagree with the
 * chart that opened it.
 */
export interface Drill {
  kind: "deals" | "customers" | "activities" | "feedback" | "invoices" | null;
  params: Record<string, string | number>;
}

export interface ReportRow {
  id: number | string | null;
  label: string;
  drill?: Drill;
  breakdown?: Record<string, { count: number; amount: number }>;
  [measure: string]: any;
}

/** A report's table layout, defined once on the server (apps.crm.reports.REPORT_COLUMNS). */
export interface ReportColumn {
  k: string;
  label: string;
  f: "rial" | "count" | "pct" | "days" | "text";
  total?: boolean;
}

export interface ReportData {
  key: string;
  axis: string;
  title: string;
  axes: string[];
  rows: ReportRow[];
  totals: Record<string, number>;
  chronological: boolean;
  stacks?: string[];
  kinds?: { code: string; label: string }[];
  axis_labels: Record<string, string>;
  /** The table layout, from the server — the export uses the same list. */
  columns: ReportColumn[];
  axis_label: string;
  window: { start: string | null; end: string | null };
}

export interface DashCard {
  key: string;
  label: string;
  value: number;
  unit: "count" | "rial" | "percent" | "days";
  sub?: Record<string, number> | null;
  drill?: Drill | null;
}

export interface CrmDashboard {
  cards: DashCard[];
  top_sellers: ReportRow[];
  funnel: ReportRow[];
  lost_reasons: ReportRow[];
  activities_by_kind: ReportRow[];
  top_active: ReportRow[];
  sources: ReportRow[];
  by_group: ReportRow[];
  trend: ReportRow[];
  incoming_trend: ReportRow[];
  new_customers_by_user: ReportRow[];
  satisfaction: ReportRow[];
  provinces: ReportRow[];
  window: { start: string | null; end: string | null };
}

export interface Deal {
  id: number;
  code: string;
  title: string;
  customer: number | null;
  customer_name: string;
  /** آرپا's party code; the customer is attached once the party is matched. */
  party_code: string;
  awaiting_match: boolean;
  owner: number | null;
  owner_name: string;
  stage: number | null;
  stage_name: string;
  status: "open" | "won" | "lost";
  status_display: string;
  province_name: string;
  group_name: string;
  source_name: string;
  reason_name: string;
  lost_note: string;
  amount_rial: string;
  cost_rial: string;
  profit_rial: string;
  discount_rial: string;
  shipping_cost_rial: string;
  other_cost_rial: string;
  margin_pct: number;
  age_days: number;
  /** Days since the last activity on it — the pipeline board sends this. */
  idle_days?: number | null;
  opened_at: string;
  opened_jalali: string;
  closed_at: string | null;
  closed_jalali: string;
  expected_close_date: string | null;
  items?: DealItem[];
}

export interface DealItem {
  id: number;
  product: number;
  product_name: string;
  unit: string;
  quantity: string;
  unit_price_rial: string;
  unit_cost_rial: string;
  discount_pct: string;
  line_total: string;
  line_cost: string;
  line_profit: string;
  margin_pct: number;
}

export interface CrmCustomer {
  id: number;
  code: string;
  name_fa: string;
  kind: string;
  status: string;
  status_display: string;
  group_name: string;
  province_name: string;
  owner: number | null;
  owner_name: string;
  source_name: string;
  contact_name: string;
  phone: string;
  mobile: string;
  city: string;
  first_contact_jalali: string;
  first_won_jalali: string;
  last_activity_at: string | null;
  stats?: Record<string, number>;
  /** The 360° extras — only the detail endpoint sends these. */
  insights?: CustomerInsights;
}

export interface CustomerInsights {
  invoiced: number;
  invoice_count: number;
  unsettled: number;
  overdue_debt: number;
  last_invoice: string;
  days_quiet: number | null;
  days_since_buy: number | null;
  active_months: number;
  series: { label: string; won: number; invoiced: number }[];
  health: { score: number; label: string; reasons: { tone: "good" | "warn" | "bad"; text: string }[] };
  tasks: CrmTask[];
  invoices: CrmInvoice[];
}

export interface CrmActivity {
  id: number;
  kind: string;
  kind_display: string;
  customer: number;
  customer_name: string;
  deal: number | null;
  deal_title: string;
  owner_name: string;
  at: string;
  at_jalali: string;
  duration_min: number;
  result: string;
  result_display: string;
  note: string;
}

export interface CrmMonth {
  key: string;
  label: string;
  year: number;
  month: number;
  date_from: string;
  date_to: string;
}

export interface CrmOptions {
  /** Jalali months, newest first — computed server-side so the calendar
   *  conversion exists in exactly one implementation. */
  months: CrmMonth[];
  provinces: { id: number; name_fa: string }[];
  employees: { id: number; name: string; team: string }[];
  groups: { id: number; name_fa: string }[];
  sources: { id: number; name_fa: string }[];
  reasons: { id: number; name_fa: string; is_controllable: boolean }[];
  stages: { id: number; name_fa: string; kind: string; order: number; probability_pct: number }[];
  products: { id: number; name_fa: string; unit: string; list_price_rial: string }[];
  tags: { id: number; name_fa: string; color: string }[];
  activity_kinds: { code: string; label: string }[];
  activity_results: { code: string; label: string }[];
}

/** The open pipeline's weighted value by expected close month. */
export interface ForecastBucket {
  key: "overdue" | "this" | "next" | "later" | "none";
  label: string;
  count: number;
  amount: number;
  weighted: number;
}

export interface PipelineColumn {
  id: number;
  name_fa: string;
  kind: string;
  order: number;
  probability_pct: number;
  count: number;
  amount: number;
  weighted: number;
  deals: Deal[];
}

type Params = Record<string, any>;

/** Strip empty values so an unset filter never narrows a query by accident. */
function clean(p: Params = {}): Params {
  const out: Params = {};
  for (const [k, v] of Object.entries(p)) {
    if (v !== "" && v !== null && v !== undefined && v !== "all") out[k] = v;
  }
  return out;
}

export interface CrmMe {
  /** False for anyone outside فروش همکار — the UI hides every create/edit
   *  affordance rather than letting them fill a form and hit a 403. */
  can_edit: boolean;
  employee: number | null;
  employee_name: string;
  team: string;
  /** Supervises a team: sees everyone's records, may enter on their behalf. */
  is_manager: boolean;
  /** False for a کارشناس — the API only ever answers with their own rows, so
   *  the UI drops the controls that could only ever return those anyway. */
  sees_all: boolean;
  /** A non-manager account with no salesperson row behind it. It legitimately
   *  sees nothing, and an empty CRM has to say why rather than look broken. */
  unlinked: boolean;
  /** Which book this account works — "team" | "organizational" | "b2b" — or
   *  null for the CEO and admins, who read every department's. */
  channel: string | null;
  /** That book's name, e.g. «فروش بانکی». Empty when there is no single one. */
  channel_label: string;
}

/** Payload for creating/updating a deal, lines included. */
export interface DealInput {
  customer: number;
  title?: string;
  owner?: number | null;
  stage?: number | null;
  lead_source?: number | null;
  lost_reason?: number | null;
  lost_note?: string;
  discount_rial?: string | number;
  shipping_cost_rial?: string | number;
  other_cost_rial?: string | number;
  expected_close_date?: string | null;
  opened_at?: string;
  items: {
    product: number;
    quantity: string | number;
    unit_price_rial: string | number;
    unit_cost_rial?: string | number;
    discount_pct?: string | number;
  }[];
}


/**
 * A suspected duplicate awaiting a person.
 *
 * Both sides travel together — the CRM row and the accounting row — because
 * the screen's whole job is the comparison, and fetching the second half per
 * card would mean 160 extra requests and a list that fills in piecemeal.
 */
export interface MatchSide {
  id?: number;
  code: string;
  name_fa: string;
  phone: string;
  mobile?: string;
  city: string;
  province: string;
  national_id: string;
  economic_code: string;
  address: string;
  owner?: string;
  status_display?: string;
  deals?: number;
  invoices?: number;
  group?: string;
  rep?: string;
  terms?: string;
}

export interface MatchCandidate {
  id: number;
  source: string;
  external_id: string;
  external_name: string;
  method: string;
  method_display: string;
  score: string;
  state: "pending" | "accepted" | "rejected";
  state_display: string;
  decided_at: string | null;
  decided_by_name: string;
  crm: MatchSide;
  arpa: MatchSide;
}

export interface MatchSummary {
  by_method: { key: string; label: string; count: number }[];
  by_state: Record<string, number>;
  pending: number;
}

/**
 * One آرپا invoice. Read-only in the CRM: it is accounting's record, and an
 * edit made here would be overwritten by — or disagree with — the ledger.
 * `amount_rial` is net of discount and before VAT; returns are negative.
 */
export interface CrmInvoice {
  id: number;
  number: string;
  kind: "sale" | "return";
  kind_display: string;
  issued_at: string;
  issued_jalali: string;
  customer: number;
  customer_name: string;
  owner: number | null;
  owner_name: string;
  deal: number | null;
  deal_title: string;
  amount_rial: string;
  vat_rial: string;
  total_rial: string;
  unsettled_rial: string;
  payment_terms: string;
}

/** کارتابل امروز — the work that is owed right now, not a windowed report. */
export interface CrmToday {
  as_of: string;
  owner: number | null;
  counters: {
    overdue: number;
    /** Overdue past `thresholds.backlog_days` — counted, not listed. */
    backlog: number;
    due_today: number;
    pending_follow_up: number;
    stale_deals: number;
    quiet_customers: number;
    activities_today: number;
    open_count: number;
    open_amount: number;
    open_weighted: number;
  };
  overdue: CrmTask[];
  due_today: CrmTask[];
  upcoming: CrmTask[];
  pending_follow_up: CrmActivity[];
  stale_deals: Deal[];
  closing_soon: Deal[];
  quiet_customers: CrmCustomer[];
  thresholds: { stale_days: number; dormant_days: number; horizon_days: number; backlog_days: number };
}

export interface CrmTask {
  id: number;
  title: string;
  customer: number | null;
  customer_name: string;
  deal: number | null;
  owner: number | null;
  owner_name: string;
  kind: string;
  kind_display: string;
  due_at: string;
  due_jalali: string;
  done_at: string | null;
  is_done: boolean;
  note: string;
}

export const crmApi = {
  async options(): Promise<CrmOptions> {
    const { data } = await api.get("/crm/options/");
    return data;
  },

  /** Switch this account between the real customer file and the showroom. */
  async me(): Promise<CrmMe> {
    const { data } = await api.get("/crm/me/");
    return data;
  },

  /** Customers and deals matching `q`, scoped like the lists. */
  async search(q: string): Promise<{ customers: CrmCustomer[]; deals: Deal[] }> {
    const { data } = await api.get("/crm/search/", { params: { q } });
    return data;
  },

  async today(params: Params = {}): Promise<CrmToday> {
    const { data } = await api.get("/crm/today/", { params: clean(params) });
    return data;
  },

  async dashboard(params: Params = {}): Promise<CrmDashboard> {
    const { data } = await api.get("/crm/dashboard/", { params: clean(params) });
    return data;
  },

  async reportIndex(): Promise<{ reports: { key: string; title: string; axes: string[] }[]; axis_labels: Record<string, string> }> {
    const { data } = await api.get("/crm/reports/");
    return data;
  },

  async report(key: string, params: Params = {}): Promise<ReportData> {
    const { data } = await api.get(`/crm/reports/${key}/`, { params: clean(params) });
    return data;
  },

  async pipeline(params: Params = {}): Promise<{ columns: PipelineColumn[]; forecast: ForecastBucket[] }> {
    const { data } = await api.get("/crm/pipeline/", { params: clean(params) });
    return data;
  },

  // ---- records ---------------------------------------------------------
  async deals(params: Params = {}) {
    const { data } = await api.get("/crm/deals/", { params: clean(params) });
    return data as { count: number; results: Deal[] };
  },

  async deal(id: number): Promise<Deal> {
    const { data } = await api.get(`/crm/deals/${id}/`);
    return data;
  },

  async dealSummary(params: Params = {}) {
    const { data } = await api.get("/crm/deals/summary/", { params: clean(params) });
    return data as { count: number; amount: number; profit: number; cost: number; margin_pct: number };
  },

  async dealHistory(id: number) {
    const { data } = await api.get(`/crm/deals/${id}/history/`);
    return data as { id: number; from_name: string; to_name: string; at_jalali: string; days_in_previous: number }[];
  },

  async moveDeal(id: number, stage: number, extra: Params = {}) {
    const { data } = await api.post(`/crm/deals/${id}/move/`, { stage, ...extra });
    return data as Deal;
  },

  async customers(params: Params = {}) {
    const { data } = await api.get("/crm/customers/", { params: clean(params) });
    return data as { count: number; results: CrmCustomer[] };
  },

  async customer(id: number): Promise<CrmCustomer> {
    const { data } = await api.get(`/crm/customers/${id}/`);
    return data;
  },

  async customerTimeline(id: number) {
    const { data } = await api.get(`/crm/customers/${id}/timeline/`);
    return data as { activities: CrmActivity[]; deals: Deal[] };
  },

  async invoices(params: Params = {}) {
    const { data } = await api.get("/crm/invoices/", { params: clean(params) });
    return data as { count: number; results: CrmInvoice[] };
  },

  async activities(params: Params = {}) {
    const { data } = await api.get("/crm/activities/", { params: clean(params) });
    return data as { count: number; results: CrmActivity[] };
  },

  async activitySummary(params: Params = {}) {
    const { data } = await api.get("/crm/activities/summary/", { params: clean(params) });
    return data as { count: number; success: number; success_rate: number; customers: number; minutes: number };
  },

  async feedback(params: Params = {}) {
    const { data } = await api.get("/crm/feedback/", { params: clean(params) });
    return data as { count: number; results: any[] };
  },

  async tasks(params: Params = {}) {
    const { data } = await api.get("/crm/tasks/", { params: clean(params) });
    return data as { count: number; results: any[] };
  },

  async completeTask(id: number) {
    const { data } = await api.post(`/crm/tasks/${id}/complete/`);
    return data;
  },

  // ---- writes ----------------------------------------------------------
  async saveCustomer(payload: Record<string, any>, id?: number) {
    const { data } = id
      ? await api.patch(`/crm/customers/${id}/`, payload)
      : await api.post("/crm/customers/", payload);
    return data as CrmCustomer & { id: number };
  },

  async deleteCustomer(id: number) {
    await api.delete(`/crm/customers/${id}/`);
  },

  async saveDeal(payload: DealInput | Record<string, any>, id?: number) {
    const { data } = id
      ? await api.patch(`/crm/deals/${id}/`, payload)
      : await api.post("/crm/deals/", payload);
    return data as { id: number };
  },

  async deleteDeal(id: number) {
    await api.delete(`/crm/deals/${id}/`);
  },

  async saveActivity(payload: Record<string, any>, id?: number) {
    const { data } = id
      ? await api.patch(`/crm/activities/${id}/`, payload)
      : await api.post("/crm/activities/", payload);
    return data as CrmActivity;
  },

  async deleteActivity(id: number) {
    await api.delete(`/crm/activities/${id}/`);
  },

  async saveTask(payload: Record<string, any>, id?: number) {
    const { data } = id
      ? await api.patch(`/crm/tasks/${id}/`, payload)
      : await api.post("/crm/tasks/", payload);
    return data;
  },

  async deleteTask(id: number) {
    await api.delete(`/crm/tasks/${id}/`);
  },

  /** Fetch the records behind an aggregate row. */
  /**
   * گزارش → اکسل. The server builds the workbook: a browser-side CSV could
   * only ever hold what the screen had already fetched.
   */
  async exportReport(key: string, params: Params = {}) {
    return api.get(`/crm/reports/${key}/export/`, {
      params: clean(params), responseType: "blob",
    });
  },

  /**
   * ریز رکوردها → اکسل, every matching record rather than the page on screen.
   * It replays the same `drill` payload the drawer lists from, so the file
   * and the drawer answer the same question.
   */
  async exportDrill(d: Drill, title: string, extra: Params = {}) {
    return api.get("/crm/export/drill/", {
      params: clean({ ...d.params, kind: d.kind ?? "deals", title, ...extra }),
      responseType: "blob",
    });
  },

  async drill(d: Drill, extra: Params = {}) {
    const params = clean({ ...d.params, ...extra });
    switch (d.kind) {
      case "customers":
        return { kind: d.kind, ...(await this.customers(params)) };
      case "activities":
        return { kind: d.kind, ...(await this.activities(params)) };
      case "feedback":
        return { kind: d.kind, ...(await this.feedback(params)) };
      case "invoices":
        return { kind: d.kind, ...(await this.invoices(params)) };
      default:
        return { kind: "deals", ...(await this.deals(params)) };
    }
  },

  /**
   * Send customers to the merge queue.
   *
   * Two selected rows are queued as a pair; any other count makes the matcher
   * hunt for each one's twin. Never merges — the whole point of the queue is
   * that fusing two customers' histories is invisible once done.
   */
  /** Several deals to one stage — each still gets its own stage event. */
  async bulkMoveDeals(ids: number[], stage: number, extra: Params = {}) {
    const { data } = await api.post("/crm/deals/bulk-move/", { ids, stage, ...extra });
    return data as { moved: number };
  },

  /** Hand the selected rows to another کارشناس (managers only). */
  async bulkAssign(kind: "deals" | "customers", ids: number[], owner: number) {
    const { data } = await api.post(`/crm/${kind}/bulk-assign/`, { ids, owner });
    return data as { updated: number; owner_name: string };
  },

  async bulkReview(ids: number[]) {
    const { data } = await api.post("/crm/customers/bulk-review/", { ids });
    return data as {
      queued: number;
      pairs: { primary: string; duplicate: string; method: string }[];
      skipped: { name_fa: string; reason: string }[];
    };
  },

  /** Delete customers that carry no history; the rest come back with a reason. */
  async bulkDelete(ids: number[]) {
    const { data } = await api.post("/crm/customers/bulk-delete/", { ids });
    return data as {
      deleted: number;
      blocked: { id: number; name_fa: string; reason: string }[];
    };
  },

  // ---- merge review ------------------------------------------------------
  async matchCandidates(params: Params = {}) {
    const { data } = await api.get("/crm/match-candidates/", { params: clean(params) });
    return data as { count: number; results: MatchCandidate[] };
  },

  async matchSummary(): Promise<MatchSummary> {
    const { data } = await api.get("/crm/match-candidates/summary/");
    return data;
  },

  /** Customers sharing the party's name — the choice the «ambig» tier needs. */
  async matchAlternatives(id: number) {
    const { data } = await api.get(`/crm/match-candidates/${id}/alternatives/`);
    return data as MatchSide[];
  },

  /** «Same customer.» `customer` overrides the suggested target. */
  async acceptMatch(id: number, customer?: number) {
    const { data } = await api.post(`/crm/match-candidates/${id}/accept/`, { customer });
    return data as { state: string; customer: { id: number; name_fa: string } };
  },

  /** «Different customers» — which creates the account, rather than dropping it. */
  async rejectMatch(id: number) {
    const { data } = await api.post(`/crm/match-candidates/${id}/reject/`);
    return data as { state: string; created: { id: number; name_fa: string } };
  },
};
