import type { BoardWidget, WidgetConfig, WidgetOptions } from "@/api/dashboards";

/**
 * Grid geometry and the one rule that keeps a hand-dragged layout tidy.
 *
 * Twelve columns is the same number every dashboard tool settles on, for the
 * same reason: it divides by 2, 3, 4 and 6, so halves, thirds and quarters are
 * all reachable without fractional cards.
 */
export const COLUMNS = 12;
export const ROW_HEIGHT = 44;
export const GAP = 12;

/**
 * A widget while it is being edited.
 *
 * `uid` — not the database id — is what the canvas, the results map and the
 * editor all key off, because a card that has just been added has no id yet
 * and would otherwise be indistinguishable from every other unsaved one.
 */
export interface DraftWidget extends BoardWidget {
  uid: string;
}

let counter = 0;
export function newUid(): string {
  counter += 1;
  return `w${counter}-${Math.random().toString(36).slice(2, 7)}`;
}

export function toDraft(widgets: BoardWidget[]): DraftWidget[] {
  return widgets.map((w) => ({
    ...w,
    options: w.options ?? {},
    config: w.config ?? {},
    uid: newUid(),
  }));
}

function overlaps(a: DraftWidget, b: DraftWidget): boolean {
  return (
    a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
  );
}

/**
 * Settle every card as far up as it will go without overlapping.
 *
 * Run after each drop rather than during the drag: compacting live makes cards
 * scatter out from under the pointer, which reads as the layout fighting back.
 * `first` is the card just dropped — it is placed before the others so it keeps
 * the row it was dragged onto instead of being pushed off it.
 */
export function compact(widgets: DraftWidget[], first?: string): DraftWidget[] {
  const order = [...widgets].sort((a, b) => {
    const ay = a.uid === first ? a.y - 0.5 : a.y;
    const by = b.uid === first ? b.y - 0.5 : b.y;
    return ay - by || a.x - b.x;
  });

  const placed: DraftWidget[] = [];
  for (const widget of order) {
    let y = 0;
    // Rows are cheap and boards are small; a linear scan is clearer than an
    // interval tree and never measurably slower at this size.
    while (placed.some((p) => overlaps({ ...widget, y }, p))) y += 1;
    placed.push({ ...widget, y });
  }
  // Back into the caller's order so Vue keeps its DOM nodes in place.
  const byUid = new Map(placed.map((w) => [w.uid, w]));
  return widgets.map((w) => byUid.get(w.uid) ?? w);
}

/** The first free row under everything — where a new card lands. */
export function bottomRow(widgets: DraftWidget[]): number {
  return widgets.reduce((max, w) => Math.max(max, w.y + w.h), 0);
}

/**
 * Sensible starting size and shape per kind, so a freshly added card is
 * already readable and the manager adjusts rather than assembles.
 */
const DEFAULT_SIZE: Record<string, { w: number; h: number }> = {
  kpi: { w: 3, h: 3 },
  progress: { w: 4, h: 3 },
  gauge: { w: 3, h: 5 },
  table: { w: 6, h: 6 },
  text: { w: 4, h: 3 },
  divider: { w: 12, h: 2 },
};

export function newWidget(kind: string, widgets: DraftWidget[]): DraftWidget {
  const size = DEFAULT_SIZE[kind] ?? { w: 6, h: 6 };
  const config: WidgetConfig = { time: { mode: "selected" }, metrics: [], limit: 10 };
  const options: WidgetOptions = kind === "text" ? { text: "" } : {};
  return {
    uid: newUid(),
    kind,
    title: "",
    subtitle: "",
    x: 0,
    y: bottomRow(widgets),
    w: size.w,
    h: size.h,
    config,
    options,
  };
}

/** Quick sizes offered in the editor, for anyone who would rather not drag. */
export const SIZE_PRESETS = [
  { label: "یک‌چهارم", w: 3 },
  { label: "یک‌سوم", w: 4 },
  { label: "نصف", w: 6 },
  { label: "دوسوم", w: 8 },
  { label: "تمام‌عرض", w: 12 },
];
