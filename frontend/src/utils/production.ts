/**
 * The plant's formulas — the same ones the server applies
 * (backend/apps/production/models.py). Keep the two in step.
 */
// Any row or sum carrying the three actuals.
type Row = object;
const n = (v: unknown) => Number(v) || 0;

/** شاخص = پوز + رسید × 9.2 + ژورنال × 2.1 */
export const INDEX_WEIGHTS = { actual_pos: 1, actual_receipt: 9.2, actual_journal: 2.1 } as const;
/** معادل وزنی (کیلو) = 0.1595 × ژورنال + 1.0636 × رسید + 0.0511 × پوز */
export const WEIGHT_EQUIV = { actual_journal: 0.1595, actual_receipt: 1.0636, actual_pos: 0.0511 } as const;
export const HOURS_PER_SHIFT = 8;
/** One metre off the press is 1.035 m². */
export const PRINT_SQM_PER_METRE = 1.035;

const weigh = (r: Row, w: Record<string, number>) =>
  Object.entries(w).reduce((s, [k, f]) => s + n((r as Record<string, unknown>)[k]) * f, 0);

export const indexOf = (r: Row) => weigh(r, INDEX_WEIGHTS);
export const weightedEquivalentOf = (r: Row) => weigh(r, WEIGHT_EQUIV);

/** Waste (kg) as a share of the weight equivalent. */
export const wastePct = (wasteKg: number, weighted: number) => (weighted ? (100 * wasteKg) / weighted : 0);

/** Idle hours out of `shifts` shifts' hours. */
export const downtimePct = (hours: number, shifts: number) =>
  shifts ? (100 * hours) / (HOURS_PER_SHIFT * shifts) : 0;
