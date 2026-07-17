const FA = new Intl.NumberFormat("fa-IR");

/** Format a Rial amount compactly (میلیارد / میلیون). */
export function rial(value: number | string | null): string {
  const n = Number(value ?? 0);
  if (Math.abs(n) >= 1e9) return `${FA.format(Math.round(n / 1e8) / 10)} میلیارد`;
  if (Math.abs(n) >= 1e6) return `${FA.format(Math.round(n / 1e5) / 10)} میلیون`;
  return FA.format(n);
}

export function pct(value: number | string | null, digits = 1): string {
  const n = Number(value ?? 0);
  return `${FA.format(Number(n.toFixed(digits)))}٪`;
}

export function num(value: number | string | null): string {
  return FA.format(Number(value ?? 0));
}

/** Format a KPI value according to its unit. */
export function kpiValue(value: string | number | null, unit: string): string {
  if (value === null) return "—";
  if (unit === "rial") return rial(value);
  if (unit === "%") return pct(value);
  return num(value);
}
