import api from "./client";

/**
 * The dashboard builder's API.
 *
 * Two halves that never mix: *boards* (what the manager arranged) and
 * *queries* (what the numbers are). A widget stores only a question; the
 * answer is fetched at render time, which is what lets a board built in خرداد
 * still answer in مهر without anyone touching it.
 */

// ---------------------------------------------------------------- catalog
export interface CatalogDimension {
  key: string;
  label: string;
  kind: "category" | "month";
  choices: { value: string; label: string }[];
}

export interface CatalogMetric {
  key: string;
  label: string;
  unit: "rial" | "number" | "percent" | "ton";
  agg: string;
  description: string;
}

export interface CatalogDataset {
  key: string;
  label: string;
  section: string;
  note: string;
  has_period: boolean;
  has_status: boolean;
  dimensions: CatalogDimension[];
  metrics: CatalogMetric[];
}

export interface WidgetKind {
  key: string;
  label: string;
  group: string;
  needs_dimension: boolean;
  metrics?: number;
  no_data?: boolean;
}

export interface BoardSection {
  key: string;
  label: string;
  department: string;
  default_board: number | null;
}

export interface Catalog {
  datasets: CatalogDataset[];
  sections: BoardSection[];
  widget_kinds: WidgetKind[];
  grid_columns: number;
  can_edit: boolean;
  periods: { id: number; label: string; year: number; month: number }[];
  default_period: number | null;
}

// ---------------------------------------------------------------- boards
export type TimeMode = "selected" | "last_n" | "ytd" | "year" | "all";

export interface WidgetFilter {
  dim: string;
  op: "eq" | "ne" | "in" | "gt" | "gte" | "lt" | "lte" | "contains";
  value: string | number | string[];
}

export interface WidgetConfig {
  dataset?: string;
  metrics?: string[];
  dimension?: string | null;
  split?: string | null;
  filters?: WidgetFilter[];
  time?: { mode: TimeMode; n?: number };
  sort?: "metric_desc" | "metric_asc" | "label" | "natural";
  limit?: number;
  include_unapproved?: boolean;
}

/** Display-only choices. Nothing in here can reach the database. */
export interface WidgetOptions {
  text?: string;
  color?: string;
  showLegend?: boolean;
  showValues?: boolean;
  compare?: string; // metric key to judge the first metric against
  goal?: number;
  align?: "start" | "center";
}

export interface BoardWidget {
  id?: number;
  kind: string;
  title: string;
  subtitle: string;
  x: number;
  y: number;
  w: number;
  h: number;
  config: WidgetConfig;
  options: WidgetOptions;
  sort_order?: number;
}

export interface Board {
  id: number;
  section: string;
  section_label: string;
  title: string;
  subtitle: string;
  is_default: boolean;
  is_published: boolean;
  sort_order: number;
  owner: number | null;
  owner_name: string;
  can_edit: boolean;
  default_period: number | null;
  updated_at: string;
  widgets: BoardWidget[];
}

export type BoardSummary = Omit<Board, "widgets">;

// ---------------------------------------------------------------- results
export interface QuerySeries {
  key: string;
  name: string;
  unit: string;
  values: number[];
}

export interface QueryResult {
  dataset: string;
  dataset_label: string;
  period_label: string;
  approved_only: boolean;
  dimension?: { key: string; label: string };
  split?: { key: string; label: string };
  categories: string[];
  series: QuerySeries[];
  rows: { key: string; label: string; values: Record<string, number> }[];
  totals: Record<string, number>;
}

export const dashboardsApi = {
  async catalog(): Promise<Catalog> {
    const { data } = await api.get("/dashboards/catalog/");
    return data;
  },

  async boards(section?: string): Promise<BoardSummary[]> {
    const { data } = await api.get("/dashboards/boards/", {
      params: section ? { section } : {},
    });
    return data.results ?? data;
  },

  async board(id: number): Promise<Board> {
    const { data } = await api.get(`/dashboards/boards/${id}/`);
    return data;
  },

  async createBoard(payload: Partial<Board>): Promise<Board> {
    const { data } = await api.post("/dashboards/boards/", payload);
    return data;
  },

  async updateBoard(id: number, payload: Partial<Board>): Promise<Board> {
    const { data } = await api.patch(`/dashboards/boards/${id}/`, payload);
    return data;
  },

  async deleteBoard(id: number): Promise<void> {
    await api.delete(`/dashboards/boards/${id}/`);
  },

  async duplicate(id: number): Promise<Board> {
    const { data } = await api.post(`/dashboards/boards/${id}/duplicate/`);
    return data;
  },

  async makeDefault(id: number): Promise<Board> {
    const { data } = await api.post(`/dashboards/boards/${id}/make-default/`);
    return data;
  },

  /** One atomic save of an arrangement — see the note on the server action. */
  async saveLayout(id: number, widgets: BoardWidget[]): Promise<Board> {
    const { data } = await api.put(`/dashboards/boards/${id}/layout/`, {
      widgets: widgets.map((w, i) => ({
        id: w.id,
        kind: w.kind,
        title: w.title,
        subtitle: w.subtitle,
        x: w.x, y: w.y, w: w.w, h: w.h,
        config: w.config,
        options: w.options,
        sort_order: i,
      })),
    });
    return data;
  },

  async query(config: WidgetConfig, period?: number | null): Promise<QueryResult> {
    const { data } = await api.post("/dashboards/query/", { config, period });
    return data;
  },

  /** Every card on a board in one round trip; each result carries its own error. */
  async queryBatch(
    items: { key: string; config: WidgetConfig }[],
    period?: number | null,
  ): Promise<Record<string, { data?: QueryResult; error?: string }>> {
    const { data } = await api.post("/dashboards/query/batch/", { items, period });
    const out: Record<string, { data?: QueryResult; error?: string }> = {};
    for (const r of data.results ?? []) out[r.key] = { data: r.data, error: r.error };
    return out;
  },
};
