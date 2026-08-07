import { num, pct, rial } from "@/utils/format";

/**
 * One place that turns a number into the thing a manager reads.
 *
 * The unit travels with the metric from the server catalog, so a widget the
 * CEO built yesterday formats correctly without anyone telling the card what
 * kind of number it is holding.
 */
export function byUnit(value: number, unit: string): string {
  if (unit === "rial") return rial(value);
  if (unit === "percent") return pct(value);
  if (unit === "ton") return `${num(Math.round(value * 100) / 100)} تن`;
  return num(Math.round(value * 100) / 100);
}

/** Percent change, or null when there is nothing honest to compare against. */
export function delta(now: number, before: number): number | null {
  if (!before) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

/**
 * A change said out loud. Past ten-fold a percentage stops meaning anything —
 * the overview page learned this the hard way with «+۳۴۰٬۲۸۲٪».
 */
export function deltaText(d: number | null): string {
  if (d === null) return "";
  const abs = Math.abs(d);
  if (abs >= 900) return `${num(Math.round(abs / 100))} برابر`;
  return pct(abs);
}
