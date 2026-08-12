import type { PaymentMethodCode } from "@/api/commercial";

/**
 * روش پرداخت — *how* the money moves, kept apart from *when* it moves.
 *
 * The two are genuinely independent: «۶۰ روزه» can be settled by cheque or by
 * transfer, and folding them into one list would produce a dropdown with
 * every combination in it. The server keeps the same split.
 */
export const PAYMENT_METHODS: {
  value: PaymentMethodCode;
  label: string;
  hint?: string;
}[] = [
  { value: "cash", label: "نقدی", hint: "وجه نقد یا کارت" },
  { value: "cheque", label: "چک", hint: "سررسید روی خود چک" },
  { value: "transfer", label: "حواله بانکی", hint: "ساتنا / پایا" },
  { value: "lc", label: "اعتبار اسنادی داخلی", hint: "LC ریالی" },
  { value: "other", label: "سایر", hint: "در توضیحات بنویسید" },
];

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
