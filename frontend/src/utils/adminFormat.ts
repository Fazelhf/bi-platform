/** Persian-first formatting helpers shared across the Admin Panel. */

const FA_NUM = new Intl.NumberFormat("fa-IR");
const FA_DATE = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric", month: "2-digit", day: "2-digit",
});
const FA_DATETIME = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit",
});

export function faNum(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  return FA_NUM.format(Number(value));
}

export function faDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return FA_DATE.format(new Date(value));
}

export function faDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return FA_DATETIME.format(new Date(value));
}

const BYTE_UNITS = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"];

export function formatBytes(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!n) return "۰";
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), BYTE_UNITS.length - 1);
  return `${FA_NUM.format(Math.round((n / 1024 ** i) * 10) / 10)} ${BYTE_UNITS[i]}`;
}

/** "۳ دقیقه پیش" — relative time for activity feeds. */
export function timeAgo(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return "همین حالا";
  const steps: [number, string][] = [
    [60, "دقیقه"], [3600, "ساعت"], [86400, "روز"], [2592000, "ماه"],
  ];
  let unit = "سال";
  let amount = seconds / 31536000;
  for (let i = 0; i < steps.length; i++) {
    const [divisor, label] = steps[i];
    const next = steps[i + 1]?.[0] ?? 31536000;
    if (seconds < next) { unit = label; amount = seconds / divisor; break; }
  }
  return `${FA_NUM.format(Math.floor(amount))} ${unit} پیش`;
}

/** Seconds → "۲ روز و ۳ ساعت", for uptime. */
export function duration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (days) parts.push(`${FA_NUM.format(days)} روز`);
  if (hours) parts.push(`${FA_NUM.format(hours)} ساعت`);
  if (!days && minutes) parts.push(`${FA_NUM.format(minutes)} دقیقه`);
  return parts.join(" و ") || "کمتر از یک دقیقه";
}

/** Pull a readable message out of a DRF error response. */
export function apiError(error: any, fallback = "عملیات ناموفق بود."): string {
  const data = error?.response?.data;
  if (!data) return error?.message || fallback;
  if (typeof data === "string") return data;
  if (data.detail) return String(data.detail);
  const parts: string[] = [];
  for (const [field, value] of Object.entries(data)) {
    const text = Array.isArray(value) ? value.join("، ") : String(value);
    parts.push(field === "non_field_errors" ? text : `${field}: ${text}`);
  }
  return parts.join(" · ") || fallback;
}
