<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import {
  dashboardsApi,
  type Catalog,
  type CatalogDataset,
  type QueryResult,
  type WidgetFilter,
} from "@/api/dashboards";
import BoardWidget from "./BoardWidget.vue";
import { SIZE_PRESETS, type DraftWidget } from "./layout";

/**
 * The builder.
 *
 * The whole idea of this screen is that a manager never learns a query
 * language: they pick a picture, a source, one or more figures, and what to
 * break them down by — and see the answer while they are still choosing. The
 * preview runs through the same endpoint the live board uses, so «همین را
 * می‌خواهم» is a promise the card keeps once it is saved.
 *
 * Every option offered here comes from the server catalog. There is no list of
 * fields in this file, which is why adding a dataset on the backend makes it
 * appear in the editor with no frontend change at all.
 */
const props = defineProps<{
  widget: DraftWidget;
  catalog: Catalog;
  period: number | null;
}>();

const emit = defineEmits<{
  (e: "save", widget: DraftWidget): void;
  (e: "close"): void;
}>();

// A copy: closing with «انصراف» must leave the board exactly as it was.
const draft = reactive<DraftWidget>(JSON.parse(JSON.stringify(props.widget)));
if (!draft.config.time) draft.config.time = { mode: "selected" };
if (!draft.config.metrics) draft.config.metrics = [];
if (!draft.options) draft.options = {};

const kindMeta = computed(
  () => props.catalog.widget_kinds.find((k) => k.key === draft.kind) ?? null,
);
const isStatic = computed(() => !!kindMeta.value?.no_data);
const needsDimension = computed(() => !!kindMeta.value?.needs_dimension);
const maxMetrics = computed(() => kindMeta.value?.metrics ?? 6);

const kindGroups = computed(() => {
  const groups: Record<string, typeof props.catalog.widget_kinds> = {};
  for (const k of props.catalog.widget_kinds) (groups[k.group] ??= []).push(k);
  return groups;
});

const dataset = computed<CatalogDataset | null>(
  () => props.catalog.datasets.find((d) => d.key === draft.config.dataset) ?? null,
);

const dimensions = computed(() => dataset.value?.dimensions ?? []);
const metrics = computed(() => dataset.value?.metrics ?? []);

// ------------------------------------------------------------------ editing
function pickKind(key: string) {
  draft.kind = key;
  // Kinds disagree about how many series they can draw; trim rather than let
  // a pie silently show only the first of four chosen metrics.
  if (draft.config.metrics && draft.config.metrics.length > maxMetrics.value) {
    draft.config.metrics = draft.config.metrics.slice(0, maxMetrics.value);
  }
  if (!needsDimension.value) draft.config.split = null;
}

function pickDataset(key: string) {
  if (draft.config.dataset === key) return;
  // Metrics, dimensions and filters all name columns of the old dataset —
  // keeping any of them would produce a spec the server has to reject.
  draft.config.dataset = key;
  draft.config.metrics = [];
  draft.config.dimension = null;
  draft.config.split = null;
  draft.config.filters = [];
}

function toggleMetric(key: string) {
  const list = draft.config.metrics ?? [];
  if (list.includes(key)) {
    draft.config.metrics = list.filter((m) => m !== key);
    return;
  }
  if (maxMetrics.value === 1) {
    draft.config.metrics = [key];
    return;
  }
  if (list.length >= maxMetrics.value) return;
  draft.config.metrics = [...list, key];
}

function metricIndex(key: string): number {
  return (draft.config.metrics ?? []).indexOf(key);
}

// ------------------------------------------------------------------ filters
function addFilter() {
  const first = dimensions.value.find((d) => d.kind !== "month");
  if (!first) return;
  (draft.config.filters ??= []).push({
    dim: first.key,
    op: first.choices.length ? "eq" : "contains",
    value: first.choices[0]?.value ?? "",
  } as WidgetFilter);
}

function removeFilter(index: number) {
  draft.config.filters?.splice(index, 1);
}

function choicesFor(dimKey: string) {
  return dimensions.value.find((d) => d.key === dimKey)?.choices ?? [];
}

function onFilterDimChange(filter: WidgetFilter) {
  const choices = choicesFor(filter.dim);
  filter.op = choices.length ? "eq" : "contains";
  filter.value = choices[0]?.value ?? "";
}

// ------------------------------------------------------------------ preview
const preview = ref<QueryResult | null>(null);
const previewError = ref("");
const previewing = ref(false);
let timer: number | undefined;

const ready = computed(() => {
  if (isStatic.value) return true;
  if (!draft.config.dataset) return false;
  if (!(draft.config.metrics ?? []).length) return false;
  if (needsDimension.value && !draft.config.dimension) return false;
  return true;
});

async function runPreview() {
  if (isStatic.value) {
    preview.value = null;
    previewError.value = "";
    return;
  }
  if (!ready.value) {
    preview.value = null;
    previewError.value = "";
    return;
  }
  previewing.value = true;
  try {
    preview.value = await dashboardsApi.query(
      JSON.parse(JSON.stringify(draft.config)),
      props.period,
    );
    previewError.value = "";
  } catch (e: any) {
    preview.value = null;
    previewError.value = e?.response?.data?.detail || "این ترکیب قابل محاسبه نیست.";
  } finally {
    previewing.value = false;
  }
}

watch(
  () => JSON.stringify(draft.config),
  () => {
    window.clearTimeout(timer);
    // Long enough that typing into a filter does not fire a query per
    // keystroke, short enough that the preview feels attached to the click.
    timer = window.setTimeout(runPreview, 350);
  },
  { immediate: true },
);
onBeforeUnmount(() => window.clearTimeout(timer));

// -------------------------------------------------------------------- save
const error = ref("");

function save() {
  if (!isStatic.value) {
    if (!draft.config.dataset) return (error.value = "منبع داده را انتخاب کنید.");
    if (!(draft.config.metrics ?? []).length)
      return (error.value = "حداقل یک شاخص انتخاب کنید.");
    if (needsDimension.value && !draft.config.dimension)
      return (error.value = "برای این نوع نمودار، «تفکیک بر اساس» لازم است.");
  }
  error.value = "";
  emit("save", JSON.parse(JSON.stringify(draft)));
}

const field =
  "w-full bg-surface border border-slate-200 rounded-xl px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition";
const label = "text-xs text-slate-400 mb-1 block";
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[70] bg-black/40 flex items-start justify-center p-3 sm:p-6 overflow-y-auto" dir="rtl">
      <div class="bg-surface rounded-card shadow-pop w-full max-w-5xl my-auto flex flex-col max-h-[94vh]">
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div>
            <h2 class="font-bold text-ink">{{ widget.id ? "ویرایش ویجت" : "ویجت جدید" }}</h2>
            <p class="text-xs text-slate-400 mt-0.5">
              نوع نمایش، منبع داده و شاخص را انتخاب کنید — نتیجه همین‌جا نمایش داده می‌شود.
            </p>
          </div>
          <button class="text-slate-400 hover:text-ink text-2xl leading-none px-1" @click="emit('close')">×</button>
        </header>

        <div class="flex-1 overflow-y-auto grid grid-cols-1 lg:grid-cols-[1fr_380px]">
          <!-- ================= the form ================= -->
          <div class="p-5 space-y-5 min-w-0">
            <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

            <!-- Kind -->
            <section>
              <span :class="label">نوع نمایش</span>
              <div v-for="(kinds, group) in kindGroups" :key="group" class="mb-2">
                <p class="text-[11px] text-slate-300 mb-1">{{ group }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <button
                    v-for="k in kinds" :key="k.key"
                    class="px-3 py-1.5 rounded-xl text-xs border transition"
                    :class="draft.kind === k.key
                      ? 'bg-panel text-white border-transparent'
                      : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
                    @click="pickKind(k.key)"
                  >{{ k.label }}</button>
                </div>
              </div>
            </section>

            <!-- Titles -->
            <section class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label :class="label">عنوان</label>
                <input v-model="draft.title" :class="field" placeholder="مثلاً فروش هر کارشناس" />
              </div>
              <div>
                <label :class="label">زیرعنوان (اختیاری)</label>
                <input v-model="draft.subtitle" :class="field" />
              </div>
            </section>

            <!-- Text widget -->
            <section v-if="draft.kind === 'text'">
              <label :class="label">متن</label>
              <textarea v-model="draft.options.text" :class="field" rows="4"
                        placeholder="یادداشتی برای خواننده گزارش…"></textarea>
            </section>

            <template v-if="!isStatic">
              <!-- Dataset -->
              <section>
                <label :class="label">منبع داده</label>
                <select :value="draft.config.dataset ?? ''" :class="field"
                        @change="pickDataset(($event.target as HTMLSelectElement).value)">
                  <option value="" disabled>— انتخاب کنید —</option>
                  <option v-for="d in catalog.datasets" :key="d.key" :value="d.key">{{ d.label }}</option>
                </select>
                <p v-if="dataset?.note" class="text-[11px] text-slate-400 mt-1">{{ dataset.note }}</p>
              </section>

              <template v-if="dataset">
                <!-- Metrics -->
                <section>
                  <span :class="label">
                    شاخص‌ها
                    <span class="text-slate-300">
                      ({{ maxMetrics === 1 ? "یکی" : `حداکثر ${maxMetrics}` }})
                    </span>
                  </span>
                  <div class="flex flex-wrap gap-1.5">
                    <button
                      v-for="m in metrics" :key="m.key"
                      class="px-3 py-1.5 rounded-xl text-xs border transition flex items-center gap-1.5"
                      :class="metricIndex(m.key) >= 0
                        ? 'bg-brand-500/10 border-brand-500/40 text-brand-600'
                        : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
                      @click="toggleMetric(m.key)"
                    >
                      <span
                        v-if="metricIndex(m.key) >= 0"
                        class="w-4 h-4 rounded-full bg-brand-500 text-white text-[10px] flex items-center justify-center"
                      >{{ metricIndex(m.key) + 1 }}</span>
                      {{ m.label }}
                    </button>
                  </div>
                  <p v-if="draft.kind === 'progress' || draft.kind === 'gauge'" class="text-[11px] text-slate-400 mt-1.5">
                    شاخص اول عدد واقعی است و شاخص دوم، هدفی که با آن سنجیده می‌شود.
                  </p>
                </section>

                <!-- Breakdown -->
                <section class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label :class="label">
                      تفکیک بر اساس
                      <span v-if="needsDimension" class="text-red-400">*</span>
                    </label>
                    <select v-model="draft.config.dimension" :class="field">
                      <option :value="null">— بدون تفکیک (یک عدد) —</option>
                      <option v-for="d in dimensions" :key="d.key" :value="d.key">{{ d.label }}</option>
                    </select>
                  </div>
                  <div v-if="needsDimension">
                    <label :class="label">تفکیک دوم (اختیاری)</label>
                    <select v-model="draft.config.split" :class="field" :disabled="!draft.config.dimension">
                      <option :value="null">— ندارد —</option>
                      <option
                        v-for="d in dimensions.filter((x) => x.key !== draft.config.dimension)"
                        :key="d.key" :value="d.key"
                      >{{ d.label }}</option>
                    </select>
                    <p v-if="draft.config.split" class="text-[11px] text-slate-400 mt-1">
                      با تفکیک دوم فقط شاخص اول رسم می‌شود.
                    </p>
                  </div>
                </section>

                <!-- Period -->
                <section class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label :class="label">دوره</label>
                    <select v-model="draft.config.time!.mode" :class="field" :disabled="!dataset.has_period">
                      <option value="selected">ماه انتخاب‌شده در بالای صفحه</option>
                      <option value="last_n">چند ماه اخیر</option>
                      <option value="ytd">از ابتدای سال تا این ماه</option>
                      <option value="year">کل سال</option>
                      <option value="all">همه دوره‌ها</option>
                    </select>
                    <p v-if="!dataset.has_period" class="text-[11px] text-slate-400 mt-1">
                      این منبع داده دوره‌ای ندارد و همیشه کامل محاسبه می‌شود.
                    </p>
                  </div>
                  <div v-if="draft.config.time!.mode === 'last_n'">
                    <label :class="label">تعداد ماه</label>
                    <input v-model.number="draft.config.time!.n" type="number" min="2" max="36" :class="field" />
                  </div>
                </section>

                <!-- Filters -->
                <section>
                  <div class="flex items-center justify-between mb-1">
                    <span :class="label">فیلترها</span>
                    <button class="text-xs text-brand-600 hover:underline" @click="addFilter">+ افزودن فیلتر</button>
                  </div>
                  <div v-if="!(draft.config.filters ?? []).length" class="text-xs text-slate-400">
                    بدون فیلتر — همه ردیف‌ها محاسبه می‌شوند.
                  </div>
                  <div
                    v-for="(f, i) in draft.config.filters ?? []" :key="i"
                    class="flex flex-wrap items-center gap-2 mb-2"
                  >
                    <select v-model="f.dim" class="flex-1 min-w-[120px]" :class="field" @change="onFilterDimChange(f)">
                      <option
                        v-for="d in dimensions.filter((x) => x.kind !== 'month')"
                        :key="d.key" :value="d.key"
                      >{{ d.label }}</option>
                    </select>
                    <select v-model="f.op" class="w-24" :class="field">
                      <option value="eq">برابر</option>
                      <option value="ne">مخالف</option>
                      <option value="contains">شامل</option>
                      <option value="gt">بزرگ‌تر از</option>
                      <option value="lt">کوچک‌تر از</option>
                    </select>
                    <select
                      v-if="choicesFor(f.dim).length"
                      v-model="f.value" class="flex-1 min-w-[120px]" :class="field"
                    >
                      <option v-for="c in choicesFor(f.dim)" :key="c.value" :value="c.value">{{ c.label }}</option>
                    </select>
                    <input v-else v-model="f.value" class="flex-1 min-w-[120px]" :class="field" placeholder="مقدار" />
                    <button class="text-slate-400 hover:text-red-500 px-1" @click="removeFilter(i)">×</button>
                  </div>
                </section>

                <!-- Sorting / size / status -->
                <section class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div v-if="draft.config.dimension">
                    <label :class="label">ترتیب</label>
                    <select v-model="draft.config.sort" :class="field">
                      <option :value="undefined">بزرگ‌ترین اول</option>
                      <option value="metric_asc">کوچک‌ترین اول</option>
                      <option value="label">بر اساس نام</option>
                      <option value="natural">ترتیب طبیعی بخش</option>
                    </select>
                  </div>
                  <div v-if="draft.config.dimension">
                    <label :class="label">حداکثر ردیف</label>
                    <input v-model.number="draft.config.limit" type="number" min="1" max="200" :class="field" />
                  </div>
                  <div v-if="dataset.has_status" class="flex items-end">
                    <label class="flex items-center gap-2 text-xs text-slate-500 pb-2">
                      <input v-model="draft.config.include_unapproved" type="checkbox" class="rounded" />
                      داده تاییدنشده هم لحاظ شود
                    </label>
                  </div>
                </section>
              </template>
            </template>

            <!-- Appearance + size -->
            <section class="border-t border-slate-100 pt-4 space-y-3">
              <span :class="label">نمایش</span>
              <div class="flex flex-wrap items-center gap-4">
                <label v-if="!isStatic" class="flex items-center gap-2 text-xs text-slate-500">
                  <input v-model="draft.options.showValues" type="checkbox" class="rounded" />
                  نمایش عدد روی نمودار
                </label>
                <label v-if="!isStatic" class="flex items-center gap-2 text-xs text-slate-500">
                  <input
                    :checked="draft.options.showLegend !== false" type="checkbox" class="rounded"
                    @change="draft.options.showLegend = ($event.target as HTMLInputElement).checked"
                  />
                  نمایش راهنما
                </label>
                <label class="flex items-center gap-2 text-xs text-slate-500">
                  رنگ
                  <input
                    :value="draft.options.color || '#3b6fed'" type="color"
                    class="w-8 h-7 rounded border border-slate-200 bg-transparent"
                    @input="draft.options.color = ($event.target as HTMLInputElement).value"
                  />
                  <button
                    v-if="draft.options.color" class="text-[11px] text-slate-400 hover:underline"
                    @click="draft.options.color = undefined"
                  >پیش‌فرض</button>
                </label>
                <label v-if="draft.kind === 'gauge'" class="flex items-center gap-2 text-xs text-slate-500">
                  هدف ثابت
                  <input v-model.number="draft.options.goal" type="number" class="w-32" :class="field" />
                </label>
              </div>

              <div>
                <span :class="label">اندازه</span>
                <div class="flex flex-wrap items-center gap-1.5">
                  <button
                    v-for="p in SIZE_PRESETS" :key="p.w"
                    class="px-3 py-1.5 rounded-xl text-xs border transition"
                    :class="draft.w === p.w
                      ? 'bg-panel text-white border-transparent'
                      : 'border-slate-200 text-slate-500 hover:bg-slate-50'"
                    @click="draft.w = p.w"
                  >{{ p.label }}</button>
                  <span class="text-xs text-slate-400 mr-2">ارتفاع</span>
                  <button class="board-step" @click="draft.h = Math.max(2, draft.h - 1)">−</button>
                  <span class="text-xs text-slate-500 w-6 text-center ltr-nums">{{ draft.h }}</span>
                  <button class="board-step" @click="draft.h = Math.min(24, draft.h + 1)">+</button>
                </div>
              </div>
            </section>
          </div>

          <!-- ================= live preview ================= -->
          <aside class="bg-slate-50/60 border-r border-slate-100 p-4 lg:sticky lg:top-0 lg:h-fit">
            <div class="flex items-center justify-between mb-2">
              <p class="text-xs text-slate-400">پیش‌نمایش</p>
              <span v-if="previewing" class="text-[11px] text-slate-300">در حال محاسبه…</span>
            </div>
            <div class="h-[300px]">
              <BoardWidget
                :widget="draft"
                :result="preview"
                :error="previewError"
                :loading="previewing && !preview"
              />
            </div>
            <p v-if="!ready && !isStatic" class="text-[11px] text-slate-400 mt-2">
              برای دیدن پیش‌نمایش، منبع داده و شاخص را انتخاب کنید.
            </p>
          </aside>
        </div>

        <footer class="px-5 py-3 border-t border-slate-100 flex items-center gap-2 shrink-0">
          <button class="bg-panel text-white rounded-xl px-5 py-2 text-sm" @click="save">ذخیره ویجت</button>
          <button class="px-4 py-2 text-sm text-slate-500 hover:bg-slate-100 rounded-xl" @click="emit('close')">
            انصراف
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.board-step {
  @apply w-7 h-7 rounded-lg border border-slate-200 text-slate-500 text-sm
         hover:bg-slate-50 transition flex items-center justify-center;
}
</style>
