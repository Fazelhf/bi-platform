/**
 * Money formatting for the finance section.
 *
 * Everything is stored in Rial. The unit is a display choice, so this is the
 * only place that divides — and it always says which unit it used, because a
 * figure like «۵۶٫۶ میلیارد» means two very different things depending on the
 * answer and the page should never leave the reader guessing.
 */
import { computed, ref } from "vue";
import { financeApi, type FinanceSettings } from "@/api/finance";

const FA = new Intl.NumberFormat("fa-IR");
/** Years are not quantities — «۱٬۴۰۵» is wrong, «۱۴۰۵» is the year. */
const FA_PLAIN = new Intl.NumberFormat("fa-IR", { useGrouping: false });

export function faYear(value: number | null | undefined): string {
  return value ? FA_PLAIN.format(value) : "—";
}

const settings = ref<FinanceSettings | null>(null);
let inflight: Promise<void> | null = null;

/** Loaded once per session; every finance page shares the same answer. */
export async function loadMoneySettings(force = false) {
  if (settings.value && !force) return;
  if (!inflight || force) {
    inflight = financeApi
      .settings()
      .then((s) => { settings.value = s; })
      .catch(() => { /* the page shows its own error */ })
      .finally(() => { inflight = null; });
  }
  await inflight;
}

export function setMoneySettings(next: FinanceSettings) {
  settings.value = next;
}

export function useMoney() {
  const unit = computed(() => settings.value?.unit ?? "rial");
  const unitLabel = computed(() => (unit.value === "toman" ? "تومان" : "ریال"));
  const divisor = computed(() => settings.value?.unit_divisor ?? 1);

  /** Compact form: «۵۶٫۶ میلیارد ریال». */
  function money(value: number | string | null | undefined, withUnit = true): string {
    const raw = Number(value ?? 0) / divisor.value;
    const suffix = withUnit ? ` ${unitLabel.value}` : "";
    const abs = Math.abs(raw);
    const sign = raw < 0 ? "−" : "";
    if (abs >= 1e9) return `${sign}${FA.format(Math.round(abs / 1e8) / 10)} میلیارد${suffix}`;
    if (abs >= 1e6) return `${sign}${FA.format(Math.round(abs / 1e5) / 10)} میلیون${suffix}`;
    if (abs >= 1e3) return `${sign}${FA.format(Math.round(abs / 100) / 10)} هزار${suffix}`;
    return `${sign}${FA.format(abs)}${suffix}`;
  }

  /** Every digit, for tables where the exact figure matters. */
  function exact(value: number | string | null | undefined, withUnit = false): string {
    const raw = Number(value ?? 0) / divisor.value;
    return `${FA.format(raw)}${withUnit ? ` ${unitLabel.value}` : ""}`;
  }

  /** Chart axes need a number in the display unit, not a string. */
  function toUnit(value: number | string | null | undefined): number {
    return Number(value ?? 0) / divisor.value;
  }

  /**
   * Compact a figure that has ALREADY been converted by `toUnit` — chart
   * axes and tooltips receive display-unit numbers, so passing them back
   * through `money()` would divide a second time.
   */
  function compact(value: number | null | undefined, withUnit = false): string {
    const raw = Number(value ?? 0);
    const suffix = withUnit ? ` ${unitLabel.value}` : "";
    const abs = Math.abs(raw);
    const sign = raw < 0 ? "−" : "";
    if (abs >= 1e9) return `${sign}${FA.format(Math.round(abs / 1e8) / 10)} میلیارد${suffix}`;
    if (abs >= 1e6) return `${sign}${FA.format(Math.round(abs / 1e5) / 10)} میلیون${suffix}`;
    if (abs >= 1e3) return `${sign}${FA.format(Math.round(abs / 100) / 10)} هزار${suffix}`;
    return `${sign}${FA.format(abs)}${suffix}`;
  }

  return { unit, unitLabel, divisor, money, exact, toUnit, compact, settings };
}
