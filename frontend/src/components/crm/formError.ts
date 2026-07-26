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
  detail: "",
  non_field_errors: "",
};

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
      lines.push(label ? `${label}: ${value}` : String(value));
    }
  };
  walk(data, "");
  return lines.length ? lines.join("\n") : "ذخیره نشد.";
}
