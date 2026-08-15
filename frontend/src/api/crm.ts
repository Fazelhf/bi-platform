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
  kind: "deals" | "customers" | "activities" | "feedback" | null;
  params: Record<string, string | number>;
}

export interface ReportRow {
  id: number | string | null;
  label: string;
  drill?: Drill;
  breakdown?: Record<string, { count: number; amount: number }>;
  [measure: string]: any;
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
  customer: number;
  customer_name: string;
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
  /** Which body of data this account is reading — real file, or showroom. */
  dataset: "real" | "demo";
  /** False for anyone outside فروش همکار — the UI hides every create/edit
   *  affordance rather than letting them fill a form and hit a 403. */
  can_edit: boolean;
  employee: number | null;
  employee_name: string;
  team: string;
  is_manager: boolean;
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

export const crmApi = {
  async options(): Promise<CrmOptions> {
    const { data } = await api.get("/crm/options/");
    return data;
  },

  /** Switch this account between the real customer file and the showroom. */
  async setDataset(dataset: "real" | "demo"): Promise<{ dataset: string }> {
    const { data } = await api.post("/crm/dataset/", { dataset });
    return data;
  },

  async me(): Promise<CrmMe> {
    const { data } = await api.get("/crm/me/");
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

  async pipeline(params: Params = {}): Promise<{ columns: PipelineColumn[] }> {
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
  async drill(d: Drill, extra: Params = {}) {
    const params = clean({ ...d.params, ...extra });
    switch (d.kind) {
      case "customers":
        return { kind: d.kind, ...(await this.customers(params)) };
      case "activities":
        return { kind: d.kind, ...(await this.activities(params)) };
      case "feedback":
        return { kind: d.kind, ...(await this.feedback(params)) };
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
