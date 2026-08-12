/**
 * Matching rules for PickerField.
 *
 * Persian text does not compare cleanly with `includes()`. The same word
 * arrives written several ways depending on the keyboard someone used, and a
 * dropdown that only matches one of them is worse than no search at all —
 * the user types the name they know, sees «چیزی پیدا نشد», and concludes the
 * supplier is missing.
 *
 * So everything is folded to one shape before comparing:
 *
 * * **Arabic letters → Persian.** `ي`→`ی`, `ك`→`ک`, `ة`→`ه`. Windows and iOS
 *   Persian keyboards disagree about these, and both spellings are already in
 *   the database.
 * * **ZWNJ and spaces are ignored.** «تامین‌کننده», «تامین کننده» and
 *   «تامینکننده» are the same word to a reader and must be the same word here.
 * * **Persian and Arabic digits → Latin.** Someone searching «۴۸ گرم» must
 *   find a row stored as "48 گرم".
 * * **Diacritics dropped, case folded.** For the Latin half of the data —
 *   container numbers, brands, ports.
 */

export interface PickerOption {
  /** What gets stored. Usually an id; for free-text fields, the text itself. */
  value: string | number;
  label: string;
  /** Second line — the detail that tells two similar rows apart. */
  hint?: string;
  /** Trailing chip: a unit, a count, a status. */
  badge?: string;
  /** Extra text to search but not display (code, Latin name, phone). */
  keywords?: string;
  disabled?: boolean;
}

const ARABIC_TO_PERSIAN: Record<string, string> = {
  "ي": "ی", // ي → ی
  "ك": "ک", // ك → ک
  "ة": "ه", // ة → ه
  "ۀ": "ه", // ۀ → ه
  "أ": "ا", // أ → ا
  "إ": "ا", // إ → ا
  "آ": "ا", // آ → ا
  "ؤ": "و", // ؤ → و
  "ئ": "ی", // ئ → ی
};

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩";

/** Fold a string to its comparable shape. Spaces survive here so callers can
 *  still split the query into terms; `squash` removes them afterwards. */
export function normalise(input: unknown): string {
  return String(input ?? "")
    // Harakat, tatweel, and the bidi marks that get pasted in from Word.
    .replace(/[ً-ْـٰ‎‏]/g, "")
    .replace(/[يكةۀأإآؤئ]/g,
      (c) => ARABIC_TO_PERSIAN[c] ?? c)
    .replace(/[۰-۹]/g, (d) => String(PERSIAN_DIGITS.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String(ARABIC_DIGITS.indexOf(d)))
    .toLowerCase()
    .replace(/[‌\s]+/g, " ")
    .trim();
}

/** The haystack form: no separators at all, so «تامین کننده» finds
 *  «تامین‌کننده» whichever way either side was typed. */
function squash(input: unknown): string {
  return normalise(input).replace(/ /g, "");
}

/**
 * Does this option answer this query?
 *
 * Every term must appear somewhere in the option — label, hint or keywords —
 * but they may appear in any order and in different parts. «البرز شیرینگ»
 * finds the supplier whose name is «پلاستیک‌سازی البرز» and whose activity
 * line mentions شیرینگ, which is exactly how someone recalls a supplier they
 * have not bought from in six months.
 */
export function matches(option: PickerOption, query: string): boolean {
  const terms = normalise(query).split(" ").filter(Boolean);
  if (!terms.length) return true;
  const hay = squash(
    [option.label, option.hint, option.badge, option.keywords, option.value]
      .filter(Boolean)
      .join(" "),
  );
  return terms.every((term) => hay.includes(term.replace(/ /g, "")));
}

/**
 * Rank: an option whose label *starts* with the query is what the user meant;
 * one that merely contains it somewhere is a fallback. Without this, typing
 * «پارس» puts «کارتن‌سازی پارس مقوا» below every row that happens to mention
 * پارس in its notes.
 */
export function rank(option: PickerOption, query: string): number {
  const q = squash(query);
  if (!q) return 0;
  const label = squash(option.label);
  if (label === q) return 0;
  if (label.startsWith(q)) return 1;
  if (label.includes(q)) return 2;
  return 3;
}

/** Sort matches best-first while keeping the caller's order within a tier. */
export function ordered(options: PickerOption[], query: string): PickerOption[] {
  if (!normalise(query)) return options;
  return options
    .map((option, index) => ({ option, index, tier: rank(option, query) }))
    .sort((a, b) => a.tier - b.tier || a.index - b.index)
    .map((row) => row.option);
}
