import type { PickerOption } from "@/components/picker";

/**
 * روش پرداخت — *how* the money moves, kept apart from *when* it moves.
 *
 * The two are genuinely independent: «۶۰ روزه» can be settled by cheque or by
 * transfer, and folding them into one list would produce a dropdown with
 * every combination in it. The server keeps the same split.
 *
 * The field is free text: these are suggestions, and anything typed that is
 * not here («تهاتر»، «چک ۳ ماهه») is saved as written and offered next time.
 */
export const PAYMENT_METHODS: PickerOption[] = [
  { value: "نقدی", label: "نقدی", hint: "وجه نقد یا کارت" },
  { value: "چک", label: "چک", hint: "سررسید روی خود چک" },
  { value: "حواله بانکی", label: "حواله بانکی", hint: "ساتنا / پایا" },
  { value: "اعتبار اسنادی داخلی", label: "اعتبار اسنادی داخلی", hint: "LC ریالی" },
];

/** شرایط تحویل — where the goods are handed over, and at whose cost. */
export const DELIVERY_TERMS: PickerOption[] = [
  { value: "درب کارخانه", label: "درب کارخانه", hint: "حمل با فروشنده" },
  { value: "درب انبار فروشنده", label: "درب انبار فروشنده", hint: "حمل با ما" },
  { value: "باربری با هزینه فروشنده", label: "باربری با هزینه فروشنده" },
  { value: "باربری با هزینه خریدار", label: "باربری با هزینه خریدار" },
];

/** The defaults followed by whatever else has been typed before. */
export function withSeen(defaults: PickerOption[], seen: string[] = []): PickerOption[] {
  const known = new Set(defaults.map((o) => String(o.value)));
  return [
    ...defaults,
    ...seen.filter((v) => v && !known.has(v)).map((v) => ({ value: v, label: v })),
  ];
}

/**
 * A one-line summary of terms for a table cell.
 *
 * Returns «—» rather than an empty string when nothing is recorded, because a
 * blank cell in a comparison table reads as «شرایط ندارد» when it actually
 * means «کسی ثبت نکرده» — and those lead to opposite decisions.
 */
export function paymentSummary(row: {
  payment_term_name?: string;
  payment_method_label?: string;
  advance_pct?: string | null;
  payment_days?: number | null;
}): string {
  const parts = [row.payment_term_name, row.payment_method_label].filter(Boolean);
  return parts.length ? parts.join(" · ") : "—";
}
