/**
 * Turn a DRF error response into something a salesperson can act on.
 *
 * DRF returns {field: ["message", …]}; showing the raw JSON (or a bare
 * "خطا در ذخیره") leaves the user guessing which box is wrong, so field names
 * are translated and each message is put on its own line.
 */
const FIELD_LABELS: Record<string, string> = {
  name_fa: "نام",
  title: "عنوان",
  customer: "مشتری",
  owner: "کارشناس",
  stage: "مرحله فروش",
  lost_reason: "دلیل از دست رفتن",
  items: "اقلام",
  product: "محصول",
  quantity: "تعداد",
  unit_price_rial: "قیمت واحد",
  due_at: "موعد",
  at: "تاریخ",
  kind: "نوع",
  result: "نتیجه",
  score: "امتیاز",
  mobile: "موبایل",
  email: "ایمیل",
  code: "کد",
  attempts_left: "تلاش باقی‌مانده",
  // بازرگانی — the same helper serves that section's forms.
  material: "کالا",
  supplier: "تامین‌کننده",
  unit: "واحد",
  min_stock: "حداقل موجودی",
  requester_unit: "واحد درخواست‌کننده",
  requested_on: "تاریخ درخواست",
  needed_by: "موعد نیاز",
  ordered_on: "تاریخ سفارش",
  delivered_on: "تاریخ تحویل",
  delivery_days: "زمان تحویل",
  validity_days: "اعتبار قیمت",
  reason: "دلیل",
  quote: "استعلام",
  status: "وضعیت",
  detail: "",
  non_field_errors: "",
};

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const toFa = (s: string) => s.replace(/\d/g, (d) => FA_DIGITS[Number(d)]);

export function apiError(e: any): string {
  const data = e?.response?.data;
  if (!data) return "ارتباط با سرور برقرار نشد.";
  if (typeof data === "string") return data;

  const lines: string[] = [];
  const walk = (value: any, label: string) => {
    if (Array.isArray(value)) {
      value.forEach((v) => walk(v, label));
    } else if (value && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        const name = FIELD_LABELS[k] ?? k;
        walk(v, name ? (label ? `${label} · ${name}` : name) : label);
      }
    } else if (value !== null && value !== undefined && value !== "") {
      // Persian digits: a message that mixes ۶ and 6 reads as a bug.
      const text = typeof value === "number" ? toFa(String(value)) : String(value);
      lines.push(label ? `${label}: ${text}` : text);
    }
  };
  walk(data, "");
  return lines.length ? lines.join("\n") : "ذخیره نشد.";
}
