<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type GeoOverview, type GeoProvince, type GeoProvinceRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { useUiStore } from "@/stores/ui";
import { init, registerMap, type EChartsOption, type EChartsType } from "@/lib/echarts";
import { activePalette, isDark, labelColor, surfaceColor, TOOLTIP } from "@/components/charts/theme";
import { num, pct, rial } from "@/utils/format";
import CrmFilterBar from "@/components/crm/CrmFilterBar.vue";
import CrmExportButton from "@/components/crm/CrmExportButton.vue";
import CrmChart from "@/components/crm/CrmChart.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * فروش جغرافیایی — the country, then one province.
 *
 * Two states on one map rather than two pages: the zoom *is* the navigation,
 * and the way back is the same map flying out again, so nobody loses where
 * they were. Sales sit on the customer's province (see
 * `apps.crm.reports.geo_overview`); invoices whose customer is not matched
 * yet have no place on a map and are counted beside it instead.
 *
 * The boundaries are geoBoundaries' IRN ADM1 (OpenStreetMap, ODbL),
 * simplified and renamed to the province names DimProvince uses — so a
 * region and its row are joined by name, with no lookup table to drift.
 */
const crm = useCrmStore();
const ui = useUiStore();
const router = useRouter();

const MAP = "iran-provinces";
const el = ref<HTMLElement | null>(null);
let chart: EChartsType | null = null;
let ro: ResizeObserver | null = null;

/** Each province's bounding box, for the zoom. Filled when the map loads. */
const boxes = new Map<string, [number, number, number, number]>();
let country: [number, number, number, number] = [44, 25, 63.4, 39.8];

const overview = shallowRef<GeoOverview | null>(null);
const detail = shallowRef<GeoProvince | null>(null);
const selected = ref<GeoProvinceRow | null>(null);
const loading = ref(true);
const loadingDetail = ref(false);
const metric = ref<"amount" | "customers" | "achievement_pct">("amount");
const search = ref("");
const showIdle = ref(true);
/**
 * Tehran on the country map or on its own. Off by default: Tehran's volume
 * is the outlier that set the old scale's maximum and washed every other
 * province out. Display only — Tehran's numbers stay in every total.
 */
const showTehran = ref(false);
const TEHRAN = "تهران";

const METRICS = [
  { key: "amount", label: "فروش" },
  { key: "customers", label: "مشتری خریدار" },
  { key: "achievement_pct", label: "تحقق تارگت" },
] as const;

/** The province is the zoom, not a filter on the map's own numbers. */
function params() {
  const q: Record<string, any> = { ...crm.query };
  delete q.province;
  return q;
}

async function loadMap() {
  if (boxes.size) return;
  const geo = (await import("@/assets/geo/iran-provinces.json")).default as any;
  let minX = 180, minY = 90, maxX = -180, maxY = -90;
  for (const f of geo.features) {
    let a = 180, b = 90, c = -180, d = -90;
    for (const poly of f.geometry.coordinates) {
      for (const [x, y] of poly[0]) {
        a = Math.min(a, x); b = Math.min(b, y); c = Math.max(c, x); d = Math.max(d, y);
      }
    }
    boxes.set(f.properties.name, [a, b, c, d]);
    minX = Math.min(minX, a); minY = Math.min(minY, b); maxX = Math.max(maxX, c); maxY = Math.max(maxY, d);
  }
  country = [minX, minY, maxX, maxY];
  registerMap(MAP, geo);
}

let lastKey = "";
async function load(force = false) {
  const key = JSON.stringify(params());
  if (!force && key === lastKey) return;
  lastKey = key;
  loading.value = true;
  try {
    const [, data] = await Promise.all([loadMap(), crmApi.geo(params())]);
    overview.value = data;
    if (selected.value) {
      // Keep the zoom across a filter change; refresh what is behind it.
      selected.value = data.rows.find((r) => r.id === selected.value!.id) ?? null;
      if (selected.value) await loadDetail(selected.value.id);
    }
  } finally {
    loading.value = false;
  }
  await nextTick();
  draw();
}

async function loadDetail(id: number) {
  loadingDetail.value = true;
  try {
    detail.value = await crmApi.geoProvince(id, params());
  } finally {
    loadingDetail.value = false;
  }
}

// ---- the map ----------------------------------------------------------------
const rowsByName = computed(() => {
  const m = new Map<string, GeoProvinceRow>();
  for (const r of overview.value?.rows ?? []) m.set(r.label, r);
  return m;
});

/** The server's cut points for this metric; see `reports.color_breaks`. */
const breaks = computed<number[]>(() => {
  const s = showTehran.value ? overview.value?.scale_with_tehran : overview.value?.scale;
  const key = metric.value === "achievement_pct" ? "achievement" : metric.value;
  return s?.[key] ?? [];
});

/** Hex blend, for a sequential ramp in the palette's own colour. */
function mix(a: string, b: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

/**
 * One colour per class. Achievement is diverging — below target reads as
 * warm, at or above as green — because «80٪» and «120٪» mean opposite
 * things; amounts and counts are a light-to-strong ramp.
 */
const classColors = computed<string[]>(() => {
  void ui.chartTheme;
  const n = breaks.value.length + 1;
  if (metric.value === "achievement_pct") return ["#dc2626", "#f97316", "#facc15", "#86efac", "#16a34a"];
  const strong = activePalette().actual;
  const light = isDark() ? "#33405a" : "#dbe6fb";
  return Array.from({ length: n }, (_, i) => mix(light, strong.startsWith("#") && strong.length === 7 ? strong : "#2563eb", n === 1 ? 1 : i / (n - 1)));
});

/** A province with nothing to measure — distinct from one that measured low. */
function hasValue(r: GeoProvinceRow): boolean {
  if (metric.value === "achievement_pct") return r.target > 0;
  return r.amount !== 0 || r.customer_base > 0 || r.customers > 0;
}

const legend = computed(() => {
  const b = breaks.value;
  const c = classColors.value;
  if (!b.length) return [];
  const f = fmtMetric;
  return [
    { color: c[0], label: `کمتر از ${f(b[0])}` },
    ...b.slice(1).map((x, i) => ({ color: c[i + 1], label: `${f(b[i])} تا ${f(x)}` })),
    { color: c[b.length], label: `${f(b[b.length - 1])} و بیشتر` },
  ];
});

const hasData = computed(() => (overview.value?.rows ?? []).some((r) => Number(r[metric.value]) > 0));
const metricLabel = computed(() => METRICS.find((m) => m.key === metric.value)?.label ?? "");

function fmtMetric(v: number): string {
  if (metric.value === "amount") return rial(v);
  if (metric.value === "achievement_pct") return pct(v);
  return num(v);
}

/** Where to look, and how close. Zoom 1 is the whole country. */
function view(): { center: [number, number]; zoom: number } {
  const box = selected.value ? boxes.get(selected.value.label) : null;
  const [a, b, c, d] = box ?? country;
  if (!box) return { center: [(a + c) / 2, (b + d) / 2], zoom: 1 };
  const [ca, cb, cc, cd] = country;
  const fit = Math.min((cc - ca) / (c - a), (cd - cb) / (d - b));
  return { center: [(a + c) / 2, (b + d) / 2], zoom: Math.min(9, fit * 0.72) };
}

const option = computed<EChartsOption>(() => {
  void ui.chartTheme;
  void ui.dark;
  const p = activePalette();
  const dark = isDark();
  const sel = selected.value?.label;
  const base = dark ? "#2a2a31" : "#eef1f5";
  const border = dark ? "#3a3a44" : "#ffffff";
  const { center, zoom } = view();
  return {
    animationDurationUpdate: 900,
    animationEasingUpdate: "cubicInOut",
    tooltip: {
      ...TOOLTIP,
      trigger: "item",
      formatter: (x: any) => {
        const r = rowsByName.value.get(x.name);
        if (!r) return x.name;
        const people = [
          r.managers?.length ? `مدیر: ${r.managers.map((m) => m.name).join("، ")}` : "",
          r.experts?.length ? `کارشناس: ${r.experts.map((m) => m.name).join("، ")}` : "",
        ].filter(Boolean).join("<br/>");
        return `<b>${x.name}</b>`
          + (r.label === TEHRAN && !showTehran.value ? " <span style='opacity:.7'>(جداگانه، زیر نقشه)</span>" : "")
          + `<br/>فروش: ${rial(r.amount)}`
          + `<br/>مشتری خریدار: ${num(r.customers)} از ${num(r.customer_base)}`
          + (r.target ? `<br/>تارگت: ${rial(r.target)} · تحقق ${pct(r.achievement_pct)}` : "<br/>تارگت: ثبت نشده")
          + `<br/>سهم از کل: ${pct(r.share_pct)}`
          + (people ? `<br/>${people}` : "<br/>مسئول تعیین نشده");
      },
    },
    // Classes, not a 0..max gradient: the legend (drawn in HTML beside the
    // map) states each class's bounds, and no outlier can stretch them.
    visualMap: {
      show: false,
      type: "piecewise",
      pieces: breaks.value.length
        ? [
          { lt: breaks.value[0], color: classColors.value[0] },
          ...breaks.value.slice(1).map((b, i) => ({ gte: breaks.value[i], lt: b, color: classColors.value[i + 1] })),
          { gte: breaks.value[breaks.value.length - 1], color: classColors.value[breaks.value.length] },
        ]
        : [{ min: -Infinity, max: Infinity, color: base }],
      outOfRange: { color: base },
    },
    series: [{
      type: "map",
      map: MAP,
      roam: false,
      center,
      zoom,
      aspectScale: 0.9,
      layoutCenter: ["50%", "50%"],
      layoutSize: "96%",
      selectedMode: false,
      label: {
        show: true,
        fontSize: sel ? 13 : 9,
        color: labelColor(),
        formatter: (x: any) => (!sel || x.name === sel ? x.name : ""),
      },
      itemStyle: { areaColor: base, borderColor: border, borderWidth: 1 },
      emphasis: {
        label: { show: true, color: dark ? "#fff" : "#111", fontWeight: "bold" },
        itemStyle: { areaColor: p.target, shadowBlur: 12, shadowColor: "rgba(0,0,0,.25)" },
      },
      data: (overview.value?.rows ?? []).map((r) => ({
        name: r.label,
        // NaN = no data: drawn in the base colour, apart from the lowest class.
        // Tehran shown separately is drawn the same way and labelled so.
        value: (r.label === TEHRAN && !showTehran.value) || !hasValue(r) ? NaN : Number(r[metric.value]) || 0,
        // Zoomed in, the neighbours step back so the province reads as the
        // subject rather than one shape among many.
        itemStyle: sel
          ? (r.label === sel
            ? { borderColor: surfaceColor(), borderWidth: 2, shadowBlur: 24, shadowColor: "rgba(0,0,0,.28)", opacity: 1 }
            : { opacity: 0.45 })
          : { opacity: 1 },
      })),
    }],
  };
});

function draw() {
  if (!el.value) return;
  if (!chart) {
    chart = init(el.value, undefined, { renderer: "canvas" });
    chart.on("click", (e: any) => {
      const r = rowsByName.value.get(e.name);
      if (r) zoomTo(r);
    });
    ro = new ResizeObserver(() => chart?.resize());
    ro.observe(el.value);
  }
  chart.setOption(option.value, { notMerge: false });
}

watch(option, () => chart?.setOption(option.value));

async function zoomTo(r: GeoProvinceRow) {
  if (selected.value?.id === r.id) return;
  selected.value = r;
  detail.value = null;
  search.value = "";
  await loadDetail(r.id);
}

function back() {
  selected.value = null;
  detail.value = null;
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape" && selected.value) back();
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  await crm.loadOptions();
  await load();
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  ro?.disconnect();
  chart?.dispose();
  chart = null;
});
watch(() => JSON.stringify(params()), () => load());
watch(() => crm.revision, () => load(true));

// ---- side panel ---------------------------------------------------------------
const ranked = computed(() => (overview.value?.rows ?? []).filter((r) => r.amount || r.customer_base));
const top = computed(() => ranked.value.slice(0, 10));
const totals = computed(() => {
  const rows = overview.value?.rows ?? [];
  return {
    amount: overview.value?.total ?? 0,
    buyers: rows.reduce((s, r) => s + (r.customers || 0), 0),
    active: rows.filter((r) => r.amount > 0).length,
  };
});

const delta = computed(() => {
  const d = detail.value;
  if (!d || d.prev_amount === null || !d.prev_amount) return null;
  return ((d.amount - d.prev_amount) / Math.abs(d.prev_amount)) * 100;
});

const customers = computed(() => {
  const q = search.value.trim();
  return (detail.value?.customers ?? []).filter((c) =>
    (showIdle.value || c.amount)
    && (!q || c.label.includes(q) || c.city.includes(q) || c.owner.includes(q)),
  );
});

const trendCats = computed(() => detail.value?.trend.map((r) => r.label) ?? []);
const trendSeries = computed(() => [
  { name: "فروش", values: detail.value?.trend.map((r) => r.amount) ?? [], color: activePalette().actual },
]);
const cityCats = computed(() => detail.value?.cities.map((r) => r.label) ?? []);
const citySeries = computed(() => [{ name: "فروش", values: detail.value?.cities.map((r) => r.amount) ?? [] }]);

function jdate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("fa-IR") : "—";
}

/** Only the statuses worth flagging; an active customer is the default. */
const STATUS: Record<string, string> = { lead: "سرنخ", dormant: "راکد", lost: "از دست رفته" };

function openCustomer(id: number | null) {
  if (id) router.push({ name: "crm-customer", params: { id } });
}

/** The map's own colour, so the ranking bars read as the same measure. */
const barColor = computed(() => { void ui.chartTheme; return activePalette().actual; });

const card = "bg-surface rounded-card shadow-soft p-4 min-w-0";

// ---- Tehran, on its own ----------------------------------------------------
const tehran = computed(() => overview.value?.tehran ?? null);
/** Schematic positions only — a 2×2 of tiles, not a map of Tehran. */
const TILE = [
  { x: 10, y: 10 }, { x: 170, y: 10 }, { x: 10, y: 110 }, { x: 170, y: 110 },
];
function zoneColor(z: { amount: number; buyers: number }): string {
  const key = metric.value === "customers" ? "customers" : "amount";
  const b = tehran.value?.scale[key] ?? [];
  const v = key === "customers" ? z.buyers : z.amount;
  if (!v) return isDark() ? "#2a2a31" : "#eef1f5";
  const i = b.filter((x) => v >= x).length;
  const n = b.length + 1;
  return mix(isDark() ? "#33405a" : "#dbe6fb", "#2563eb", n === 1 ? 1 : i / (n - 1));
}
const repsAssigned = computed(() => (detail.value?.reps ?? []).filter((r) => r.assigned));
const repsOther = computed(() => (detail.value?.reps ?? []).filter((r) => !r.assigned));
</script>

<template>
  <div class="space-y-4">
    <CrmFilterBar />

    <div class="grid xl:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
      <!-- ================= Map ================= -->
      <div :class="card" class="relative overflow-hidden">
        <div class="flex flex-wrap items-center gap-2 mb-2 min-h-[36px]">
          <Transition name="crumb" mode="out-in">
            <div v-if="selected" key="zoomed" class="flex items-center gap-2">
              <button
                class="flex items-center gap-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-ink text-sm px-3 py-1.5 transition"
                title="بازگشت به نقشه‌ی ایران (Esc)"
                @click="back"
              >
                <NavIcon name="chevron" :size="16" class="rotate-180" />
                ایران
              </button>
              <span class="text-slate-300">/</span>
              <h2 class="font-bold text-ink">{{ selected.label }}</h2>
            </div>
            <h2 v-else key="country" class="font-bold text-ink">فروش به تفکیک استان</h2>
          </Transition>
          <span class="flex-1"></span>
          <CrmExportButton
            url="/crm/geo/"
            :params="{ ...params(), export: 1, ...(selected ? { province: selected.id } : {}) }"
            :title="selected ? `فروش ${selected.label}` : 'فروش جغرافیایی'"
            :total="overview?.rows.length ?? 0" subtle
          />
          <label v-if="!selected" class="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer" title="فقط نمایش؛ اعداد تهران در جمع‌ها هست">
            <input v-model="showTehran" type="checkbox" class="rounded" />
            تهران روی نقشه
          </label>
          <div v-if="!selected" class="flex bg-slate-100 rounded-xl p-0.5 text-xs">
            <button
              v-for="m in METRICS" :key="m.key"
              class="px-3 py-1.5 rounded-lg transition"
              :class="metric === m.key ? 'bg-surface shadow-soft text-ink' : 'text-slate-500 hover:text-ink'"
              @click="metric = m.key"
            >{{ m.label }}</button>
          </div>
        </div>

        <div class="relative">
          <div ref="el" class="w-full h-[440px] sm:h-[560px] map-canvas" :class="{ 'is-ready': !loading }"></div>
          <div v-if="loading && !overview" class="absolute inset-0 grid place-items-center">
            <Skeleton class="w-3/4 h-3/4 rounded-card" />
          </div>
          <p v-if="!selected && !loading" class="absolute bottom-3 right-3 text-[11px] text-slate-400 pointer-events-none">
            روی هر استان بزنید تا جزئیاتش باز شود
          </p>
        </div>
        <!-- The legend states the metric and every class's bounds. -->
        <div v-if="!selected && hasData" class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
          <span class="font-semibold text-ink">رنگ: {{ metricLabel }}</span>
          <span v-for="l in legend" :key="l.label" class="flex items-center gap-1">
            <span class="inline-block w-3 h-3 rounded-sm" :style="{ background: l.color }"></span>{{ l.label }}
          </span>
          <span class="flex items-center gap-1">
            <span class="inline-block w-3 h-3 rounded-sm border border-slate-300 bg-slate-100"></span>
            {{ metric === "achievement_pct" ? "بدون تارگت" : "بدون داده" }}
          </span>
          <span v-if="!showTehran" class="text-slate-400">· تهران جدا، زیر نقشه</span>
        </div>
      </div>

      <!-- ================= Side panel ================= -->
      <Transition name="panel" mode="out-in">
        <!-- Country -->
        <div v-if="!selected" key="country" class="space-y-4">
          <div :class="card">
            <p class="text-xs text-slate-400">فروش کل کشور</p>
            <p class="text-2xl font-bold text-ink mt-1">{{ rial(totals.amount) }}</p>
            <div class="grid grid-cols-2 gap-3 mt-4 text-sm">
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">استان فعال</p>
                <p class="font-semibold text-ink mt-0.5">{{ num(totals.active) }} از ۳۱</p>
              </div>
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">مشتری خریدار</p>
                <p class="font-semibold text-ink mt-0.5">{{ num(totals.buyers) }}</p>
              </div>
            </div>
            <p v-if="overview?.unplaced.amount" class="text-[11px] text-amber-600 mt-3 leading-5">
              {{ rial(overview.unplaced.amount) }} فروش ({{ num(overview.unplaced.count) }} فاکتور)
              هنوز به مشتری یا استانی وصل نیست و روی نقشه نیامده است.
            </p>
          </div>

          <div :class="card">
            <p class="text-sm font-semibold text-ink mb-3">استان‌های برتر</p>
            <EmptyState v-if="!loading && !top.length" title="در این بازه فروشی ثبت نشده" />
            <ol class="space-y-1">
              <li v-for="(r, i) in top" :key="r.id ?? i">
                <button
                  class="w-full flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-slate-50 text-right transition group"
                  @click="zoomTo(r)"
                >
                  <span class="w-6 h-6 rounded-lg bg-slate-100 text-slate-500 text-[11px] grid place-items-center shrink-0">{{ num(i + 1) }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="flex items-baseline justify-between gap-2">
                      <span class="text-sm text-ink truncate">{{ r.label }}</span>
                      <span class="text-xs text-ink whitespace-nowrap">{{ rial(r.amount) }}</span>
                    </span>
                    <span class="block h-1.5 rounded-full bg-slate-100 mt-1.5 overflow-hidden">
                      <span class="block h-full rounded-full bar" :style="{ width: `${Math.max(2, r.share_pct)}%`, background: barColor }"></span>
                    </span>
                  </span>
                </button>
              </li>
            </ol>
          </div>
        </div>

        <!-- Province -->
        <div v-else key="province" class="space-y-4">
          <div :class="card">
            <div class="flex items-start justify-between gap-2">
              <div>
                <p class="text-xs text-slate-400">فروش {{ selected.label }}</p>
                <p class="text-2xl font-bold text-ink mt-1">{{ rial(detail?.amount ?? selected.amount) }}</p>
              </div>
              <span
                v-if="delta !== null"
                class="text-xs font-medium rounded-full px-2 py-1"
                :class="delta >= 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-500'"
                title="نسبت به دوره‌ی قبل"
              >{{ delta >= 0 ? "▲" : "▼" }} {{ pct(Math.abs(delta)) }}</span>
            </div>
            <div class="grid grid-cols-2 gap-3 mt-4 text-sm">
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">مشتری خریدار</p>
                <p class="font-semibold text-ink mt-0.5">
                  {{ num(detail?.buyers ?? selected.customers) }}
                  <span class="text-slate-400 font-normal text-xs">از {{ num(detail?.customer_base ?? selected.customer_base) }}</span>
                </p>
              </div>
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">فاکتور</p>
                <p class="font-semibold text-ink mt-0.5">{{ num(detail?.count ?? selected.count) }}</p>
              </div>
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">مانده‌ی تسویه‌نشده</p>
                <p class="font-semibold mt-0.5" :class="detail?.unsettled ? 'text-amber-600' : 'text-ink'">{{ rial(detail?.unsettled ?? 0) }}</p>
              </div>
              <div class="bg-slate-50 rounded-xl p-3">
                <p class="text-[11px] text-slate-400">سهم از کل</p>
                <p class="font-semibold text-ink mt-0.5">{{ pct(selected.share_pct) }}</p>
              </div>
            </div>
            <div v-if="selected.target" class="mt-4">
              <div class="flex justify-between text-[11px] text-slate-400 mb-1">
                <span>تحقق تارگت</span>
                <span>{{ pct(selected.achievement_pct) }} از {{ rial(selected.target) }}</span>
              </div>
              <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-700"
                  :class="selected.achievement_pct >= 100 ? 'bg-emerald-500' : selected.achievement_pct >= 70 ? 'bg-amber-500' : 'bg-red-500'"
                  :style="{ width: `${Math.min(100, selected.achievement_pct)}%` }"
                ></div>
              </div>
            </div>
          </div>

          <div :class="card">
            <p class="text-sm font-semibold text-ink mb-1">مسئولان این استان</p>
            <p class="text-xs text-slate-500 mb-3">
              مدیر فروش: {{ detail?.managers?.map((m) => m.name).join("، ") || "تعیین نشده" }}
            </p>
            <Skeleton v-if="loadingDetail" class="h-16 rounded-xl" />
            <template v-else>
              <p class="text-[11px] text-slate-400 mb-1">کارشناسان این استان</p>
              <p v-if="!repsAssigned.length" class="text-xs text-slate-400 mb-2">کارشناسی به این استان تخصیص نیافته</p>
              <ul class="space-y-2 text-sm mb-3">
                <li v-for="r in repsAssigned" :key="'a' + r.id" class="flex justify-between gap-2">
                  <span class="text-ink truncate">{{ r.label }}</span>
                  <span class="text-ink whitespace-nowrap">{{ rial(r.amount) }}</span>
                </li>
              </ul>
              <template v-if="repsOther.length">
                <p class="text-[11px] text-slate-400 mb-1">سایر کارشناسان (فروش در این استان)</p>
                <ul class="space-y-2 text-sm">
                  <li v-for="r in repsOther" :key="'o' + String(r.id)" class="flex justify-between gap-2">
                    <span class="text-slate-600 truncate">{{ r.label }}</span>
                    <span class="text-ink whitespace-nowrap">{{ rial(r.amount) }}</span>
                  </li>
                </ul>
              </template>
              <p class="text-[10px] text-slate-400 mt-2">هر فاکتور یک‌بار و به نام کارشناس همان فاکتور شمرده می‌شود.</p>
            </template>
          </div>
        </div>
      </Transition>
    </div>

    <!-- ================= Tehran by sales zone (فروش همکار) ================= -->
    <div v-if="!selected && !showTehran && tehran" :class="card">
      <div class="flex flex-wrap items-baseline gap-2 mb-3">
        <h2 class="font-bold text-ink">تهران به تفکیک محدوده‌ی فروش</h2>
        <span class="text-xs text-slate-400">فروش همکار · {{ rial(tehran.total) }}</span>
        <span class="flex-1"></span>
        <span class="text-[11px] text-slate-400">نقشه‌ی شماتیک؛ مرز جغرافیایی واقعی ندارد</span>
      </div>
      <div class="grid md:grid-cols-[340px_minmax(0,1fr)] gap-4 items-start">
        <svg viewBox="0 0 330 210" class="w-full max-w-[340px]" role="img" aria-label="نقشه‌ی شماتیک محدوده‌های تهران">
          <g v-for="(z, i) in tehran.rows.slice(0, 4)" :key="z.id" class="cursor-pointer" @click="crm.openDrill(z.drill, `فاکتورهای ${z.label}`)">
            <rect :x="TILE[i].x" :y="TILE[i].y" width="150" height="90" rx="14" :fill="zoneColor(z)" stroke="white" stroke-width="2" />
            <text :x="TILE[i].x + 75" :y="TILE[i].y + 40" text-anchor="middle" class="fill-current text-ink" font-size="14" font-weight="700">{{ z.label }}</text>
            <text :x="TILE[i].x + 75" :y="TILE[i].y + 62" text-anchor="middle" class="fill-current text-slate-600" font-size="11">{{ rial(z.amount) }}</text>
          </g>
        </svg>
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-medium py-1.5">محدوده</th>
              <th class="text-left font-medium">فروش</th>
              <th class="text-left font-medium">خریدار</th>
              <th class="text-left font-medium">مشتری</th>
              <th class="text-right font-medium pr-3">مسئول</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="z in tehran.rows" :key="z.id" class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                @click="crm.openDrill(z.drill, `فاکتورهای ${z.label}`)">
              <td class="py-2 text-ink">{{ z.label }}</td>
              <td class="text-left ltr-nums">{{ rial(z.amount) }} <span class="text-slate-400">({{ pct(z.share_pct) }})</span></td>
              <td class="text-left ltr-nums">{{ num(z.buyers) }}</td>
              <td class="text-left ltr-nums">{{ num(z.customer_base) }}</td>
              <td class="pr-3 text-slate-500">{{ [...z.managers, ...z.experts].map((p) => p.name).join("، ") || "—" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="tehran.unzoned_customers" class="text-[11px] text-amber-600 mt-3">
        {{ num(tehran.unzoned_customers) }} مشتری تهران هنوز محدوده ندارند و در «{{ tehran.default_zone }}» شمرده شده‌اند؛
        محدوده را در فهرست مشتریان (ستون استان) تعیین کنید.
      </p>
    </div>

    <!-- ================= Province detail, below the map ================= -->
    <Transition name="rise">
      <div v-if="selected" class="space-y-4">
        <div v-if="loadingDetail && !detail" class="grid lg:grid-cols-3 gap-4">
          <Skeleton v-for="i in 3" :key="i" class="h-56 rounded-card" />
        </div>
        <template v-else-if="detail">
          <div class="grid lg:grid-cols-3 gap-4">
            <div :class="card">
              <p class="text-sm font-semibold text-ink mb-3">روند فروش</p>
              <CrmChart :categories="trendCats" :series="trendSeries" format="rial" :height="220" />
            </div>
            <div :class="card">
              <p class="text-sm font-semibold text-ink mb-3">شهرها</p>
              <CrmChart v-if="cityCats.length" :categories="cityCats" :series="citySeries" format="rial" :height="220" horizontal />
              <EmptyState v-else title="فروشی ثبت نشده" />
            </div>
            <div :class="card">
              <p class="text-sm font-semibold text-ink mb-3">پرفروش‌ترین کالاها</p>
              <EmptyState v-if="!detail.products.length" title="فروشی ثبت نشده" />
              <ul class="space-y-2.5">
                <li v-for="p in detail.products" :key="p.label">
                  <div class="flex justify-between gap-2 text-xs">
                    <span class="text-slate-600 truncate">{{ p.label }}</span>
                    <span class="text-ink whitespace-nowrap">{{ rial(p.amount) }}</span>
                  </div>
                  <div class="h-1.5 rounded-full bg-slate-100 mt-1 overflow-hidden">
                    <div class="h-full rounded-full bar" :style="{ width: `${(p.amount / (detail.products[0].amount || 1)) * 100}%`, background: barColor }"></div>
                  </div>
                </li>
              </ul>
            </div>
          </div>

          <div class="grid lg:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start">
            <!-- Customers -->
            <div :class="card">
              <div class="flex flex-wrap items-center gap-2 mb-3">
                <p class="text-sm font-semibold text-ink">مشتریان {{ detail.label }}</p>
                <span class="text-[11px] bg-slate-100 text-slate-500 rounded-full px-2 py-0.5">{{ num(customers.length) }}</span>
                <span class="flex-1"></span>
                <label class="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer">
                  <input v-model="showIdle" type="checkbox" class="rounded" />
                  بدون خرید هم
                </label>
                <input
                  v-model="search"
                  class="bg-slate-100 rounded-xl px-3 py-1.5 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 w-44"
                  placeholder="جستجوی نام، شهر، کارشناس"
                />
              </div>
              <div class="overflow-x-auto max-h-[480px] overflow-y-auto">
                <table class="w-full text-xs min-w-[640px]">
                  <thead class="sticky top-0 bg-surface">
                    <tr class="text-slate-400">
                      <th class="text-right font-medium py-2">مشتری</th>
                      <th class="text-right font-medium py-2">شهر</th>
                      <th class="text-right font-medium py-2">کارشناس</th>
                      <th class="text-left font-medium py-2">خرید</th>
                      <th class="text-left font-medium py-2">فاکتور</th>
                      <th class="text-left font-medium py-2">مانده</th>
                      <th class="text-left font-medium py-2">آخرین خرید</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="c in customers" :key="c.id"
                      class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                      @click="openCustomer(c.id)"
                    >
                      <td class="py-2">
                        <span class="text-ink">{{ c.label }}</span>
                        <span v-if="STATUS[c.status]" class="text-[10px] text-slate-400 mr-1">· {{ STATUS[c.status] }}</span>
                      </td>
                      <td class="py-2 text-slate-500">{{ c.city || "—" }}</td>
                      <td class="py-2 text-slate-500 truncate max-w-[120px]">{{ c.owner || "—" }}</td>
                      <td class="py-2 text-left whitespace-nowrap" :class="c.amount ? 'text-ink font-medium' : 'text-slate-300'">{{ c.amount ? rial(c.amount) : "—" }}</td>
                      <td class="py-2 text-left text-slate-500">{{ c.count ? num(c.count) : "—" }}</td>
                      <td class="py-2 text-left whitespace-nowrap" :class="c.unsettled ? 'text-amber-600' : 'text-slate-300'">{{ c.unsettled ? rial(c.unsettled) : "—" }}</td>
                      <td class="py-2 text-left text-slate-500 whitespace-nowrap">{{ jdate(c.last_purchase) }}</td>
                    </tr>
                  </tbody>
                </table>
                <EmptyState v-if="!customers.length" title="مشتری‌ای پیدا نشد" />
              </div>
            </div>

            <!-- Recent invoices -->
            <div :class="card">
              <div class="flex items-center justify-between mb-3">
                <p class="text-sm font-semibold text-ink">آخرین خریدها</p>
                <button
                  class="text-xs text-slate-500 hover:text-ink"
                  @click="crm.openDrill(detail.drill, `فاکتورهای ${detail.label}`)"
                >همه فاکتورها</button>
              </div>
              <EmptyState v-if="!detail.recent.length" title="خریدی ثبت نشده" />
              <ul class="divide-y divide-slate-100">
                <li
                  v-for="inv in detail.recent" :key="inv.id"
                  class="py-2.5 flex items-center gap-3 cursor-pointer hover:bg-slate-50 rounded-lg px-1"
                  @click="openCustomer(inv.customer_id)"
                >
                  <span
                    class="w-8 h-8 rounded-xl grid place-items-center shrink-0 text-[10px]"
                    :class="inv.kind === 'return' ? 'bg-red-50 text-red-500' : 'bg-emerald-50 text-emerald-600'"
                  >{{ inv.kind === "return" ? "مرجوع" : "فروش" }}</span>
                  <span class="flex-1 min-w-0">
                    <span class="block text-sm text-ink truncate">{{ inv.customer }}</span>
                    <span class="block text-[11px] text-slate-400">{{ jdate(inv.date) }} · برگه {{ inv.number }}</span>
                  </span>
                  <span class="text-sm whitespace-nowrap" :class="inv.amount < 0 ? 'text-red-500' : 'text-ink'">{{ rial(inv.amount) }}</span>
                </li>
              </ul>
            </div>
          </div>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.map-canvas { opacity: 0; transform: scale(0.97); transition: opacity 0.6s ease, transform 0.8s cubic-bezier(0.2, 0.8, 0.2, 1); }
.map-canvas.is-ready { opacity: 1; transform: none; }


.panel-enter-active, .panel-leave-active { transition: opacity 0.35s ease, transform 0.45s cubic-bezier(0.2, 0.8, 0.2, 1); }
.panel-enter-from { opacity: 0; transform: translateX(-24px); }
.panel-leave-to { opacity: 0; transform: translateX(24px); }

.crumb-enter-active, .crumb-leave-active { transition: opacity 0.25s ease, transform 0.3s ease; }
.crumb-enter-from, .crumb-leave-to { opacity: 0; transform: translateY(-6px); }

.rise-enter-active { transition: opacity 0.5s ease 0.35s, transform 0.6s cubic-bezier(0.2, 0.8, 0.2, 1) 0.35s; }
.rise-leave-active { transition: opacity 0.25s ease, transform 0.3s ease; }
.rise-enter-from { opacity: 0; transform: translateY(28px); }
.rise-leave-to { opacity: 0; transform: translateY(12px); }

@media (prefers-reduced-motion: reduce) {
  .map-canvas, .panel-enter-active, .panel-leave-active, .crumb-enter-active,
  .crumb-leave-active, .rise-enter-active, .rise-leave-active { transition: none; }
}
</style>
