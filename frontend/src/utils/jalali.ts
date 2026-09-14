/**
 * Jalali ⇄ Gregorian, with no dependency and no conversion table.
 *
 * The browser already ships an exact Persian calendar — `Intl` with the
 * `persian` calendar knows every leap year, including the irregular ones a
 * hand-written 33-year cycle gets wrong. What it does not offer is the
 * direction a date *picker* needs: given a Jalali day the user clicked, which
 * Gregorian day is that?
 *
 * So that direction is solved by search rather than by arithmetic. Start from
 * a Gregorian date near the answer, ask Intl what Jalali date it is, step by
 * the difference, repeat. The first step lands within a day or two and the
 * second lands exactly, because once the year matches, the within-year
 * distance is exact: Jalali month lengths are fixed for months 1–11, and the
 * only variable one — اسفند — is never *crossed* by a within-year step that
 * starts and ends in the same year.
 *
 * Everything the platform stores stays Gregorian ISO. This module is the
 * boundary: Jalali is what a person reads and clicks, ISO is what is sent.
 */

const PARTS = new Intl.DateTimeFormat("en-US-u-ca-persian", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  timeZone: "UTC",
});

export interface JalaliDate {
  jy: number;
  jm: number;
  jd: number;
}

export const MONTH_NAMES = [
  "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
  "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
];

/** Saturday first, the way a Persian calendar is read. */
export const WEEKDAY_NAMES = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

/**
 * Days from the start of the Jalali year to (jm, jd).
 *
 * Independent of leap years: the first six months are always 31 days and the
 * next five always 30, so only اسفند varies and nothing before it does.
 */
function ordinal(jm: number, jd: number): number {
  return (jm <= 6 ? (jm - 1) * 31 : 186 + (jm - 7) * 30) + jd;
}

function addDays(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 86_400_000);
}

/** The Jalali date of a UTC-anchored Gregorian day. */
export function toJalali(date: Date): JalaliDate {
  const parts = PARTS.formatToParts(date);
  const get = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value ?? 0);
  return { jy: get("year"), jm: get("month"), jd: get("day") };
}

/**
 * The Gregorian day that *is* this Jalali day, as a UTC-midnight Date.
 *
 * Converges in two steps; the loop bound is a guard, not a plan. If it ever
 * failed to converge it would return the closest day found rather than throw —
 * a date picker that crashes is worse than one that is a day out, and the
 * bound is generous enough that neither has been observed.
 */
export function toGregorian({ jy, jm, jd }: JalaliDate): Date {
  // Nowruz is 20 or 21 March, so this anchor is always within a few days of
  // the start of the requested Jalali year.
  let d = new Date(Date.UTC(jy + 621, 2, 21));
  for (let i = 0; i < 8; i++) {
    const cur = toJalali(d);
    if (cur.jy === jy && cur.jm === jm && cur.jd === jd) return d;
    const step =
      (jy - cur.jy) * 365 + (ordinal(jm, jd) - ordinal(cur.jm, cur.jd));
    if (step === 0) break;
    d = addDays(d, step);
  }
  // Last resort: walk the neighbourhood. Cheap, and it cannot loop.
  for (let off = -4; off <= 4; off++) {
    const probe = addDays(d, off);
    const cur = toJalali(probe);
    if (cur.jy === jy && cur.jm === jm && cur.jd === jd) return probe;
  }
  return d;
}

/** How many days اسفند (or any month) has in this particular year. */
export function monthLength(jy: number, jm: number): number {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  // اسفند: 29 or 30. Ask the calendar rather than guess the cycle.
  return toJalali(addDays(toGregorian({ jy, jm: 12, jd: 1 }), 29)).jm === 12
    ? 30
    : 29;
}

/** Which column a month's first day falls in, Saturday being column 0. */
export function firstWeekdayColumn(jy: number, jm: number): number {
  // getUTCDay(): 0 = Sunday … 6 = Saturday. Saturday must map to 0.
  return (toGregorian({ jy, jm, jd: 1 }).getUTCDay() + 1) % 7;
}

export function addMonths({ jy, jm, jd }: JalaliDate, delta: number): JalaliDate {
  const total = (jy * 12 + (jm - 1)) + delta;
  const y = Math.floor(total / 12);
  const m = (total % 12) + 1;
  return { jy: y, jm: m, jd: Math.min(jd, monthLength(y, m)) };
}

// --------------------------------------------------------------------------
// The string forms the rest of the app passes around
// --------------------------------------------------------------------------
const pad = (n: number) => String(n).padStart(2, "0");

/**
 * ISO strings here are *local wall-clock* dates, matching what `<input
 * type="date">` and `type="datetime-local"` produced before this existed —
 * every caller already treats them that way, and reinterpreting them as UTC
 * would shift every stored follow-up by hours.
 */
export function isoToJalali(iso: string): JalaliDate | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return null;
  return toJalali(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])));
}

export function jalaliToIso(j: JalaliDate): string {
  const g = toGregorian(j);
  return `${g.getUTCFullYear()}-${pad(g.getUTCMonth() + 1)}-${pad(g.getUTCDate())}`;
}

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export const faDigits = (s: string | number) =>
  String(s).replace(/\d/g, (d) => FA_DIGITS[Number(d)]);

/** «۱۴ مرداد ۱۴۰۴» — the label under a picker and in a read-only field. */
export function jalaliLabel(iso: string, withTime = false): string {
  const j = isoToJalali(iso);
  if (!j) return "";
  const date = `${faDigits(j.jd)} ${MONTH_NAMES[j.jm - 1]} ${faDigits(j.jy)}`;
  if (!withTime) return date;
  const t = /T(\d{2}):(\d{2})/.exec(iso);
  return t ? `${date} · ساعت ${faDigits(t[1])}:${faDigits(t[2])}` : date;
}

/** Today, as the local wall-clock day rather than a UTC instant. */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
