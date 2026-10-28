<script setup lang="ts">
import { computed } from "vue";
import { useCrmStore } from "@/stores/crm";
import { jalaliLabel } from "@/utils/jalali";
import JalaliDateField from "@/components/JalaliDateField.vue";

/** The one filter bar every CRM page shares (state lives in the store). */
const crm = useCrmStore();
const emit = defineEmits<{ (e: "change"): void }>();

const months = computed(() => crm.options?.months ?? []);
const employees = computed(() => crm.options?.employees ?? []);
const groups = computed(() => crm.options?.groups ?? []);
const sources = computed(() => crm.options?.sources ?? []);
const provinces = computed(() => crm.options?.provinces ?? []);

function changed() { emit("change"); }

/**
 * The period is one control with three modes — a rolling span, one month, or
 * a custom range — so a month and a range can never both be «on». The
 * month or the dates sit right next to the mode that uses them.
 */
const MODES = [
  { key: "span", label: "بازه‌ی اخیر" },
  { key: "month", label: "یک ماه" },
  { key: "custom", label: "بازه دلخواه" },
] as const;
const SPANS = [
  { key: "current", label: "ماه جاری" },
  { key: "last3", label: "۳ ماه اخیر" },
  { key: "last6", label: "۶ ماه اخیر" },
  { key: "last12", label: "۱۲ ماه اخیر" },
];
const mode = computed(() =>
  crm.filters.range === "month" || crm.filters.range === "custom" ? crm.filters.range : "span",
);
function setMode(m: string) {
  if (m === mode.value) return;
  if (m === "span") crm.filters.range = "last6";
  else if (m === "month") {
    crm.filters.range = "month";
    if (!crm.filters.month) crm.filters.month = months.value[0]?.key ?? "";
  } else {
    // Start the custom range from what was on screen, so switching does not
    // jump to an empty window.
    const q = crm.query;
    crm.filters.date_from = crm.filters.date_from || q.date_from || "";
    crm.filters.date_to = crm.filters.date_to || q.date_to || "";
    crm.filters.range = "custom";
  }
  changed();
}

/** The exact days the reports cover, in Jalali — what every card on the page sums. */
const periodText = computed(() => {
  const q = crm.query;
  if (!q.date_from && !q.date_to) return "";
  return `${q.date_from ? jalaliLabel(q.date_from) : "…"} تا ${q.date_to ? jalaliLabel(q.date_to) : "…"}`;
});
const badRange = computed(() =>
  crm.filters.range === "custom" && !!crm.filters.date_from && !!crm.filters.date_to
  && crm.filters.date_from > crm.filters.date_to,
);

const active = computed(() =>
  [crm.filters.owner, crm.filters.group, crm.filters.source, crm.filters.province]
    .filter((v) => v !== "").length,
);

const sel = "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none border-0 focus:ring-2 focus:ring-slate-300 min-w-0";
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2 no-print">
    <!-- Period: mode, then the one input that mode needs, side by side. -->
    <div class="flex flex-wrap items-center gap-2" role="group" aria-label="دوره‌ی گزارش">
      <div class="flex bg-slate-100 rounded-xl p-0.5 text-xs">
        <button
          v-for="m in MODES" :key="m.key" type="button"
          class="px-3 py-1.5 rounded-lg transition"
          :class="mode === m.key ? 'bg-surface shadow-soft text-ink' : 'text-slate-500 hover:text-ink'"
          :aria-pressed="mode === m.key"
          @click="setMode(m.key)"
        >{{ m.label }}</button>
      </div>
      <select v-if="mode === 'span'" v-model="crm.filters.range" :class="sel" aria-label="بازه" @change="changed">
        <option v-for="s in SPANS" :key="s.key" :value="s.key">{{ s.label }}</option>
      </select>
      <select v-else-if="mode === 'month'" v-model="crm.filters.month" :class="sel" aria-label="ماه" @change="changed">
        <option v-for="m in months" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <template v-else>
        <JalaliDateField v-model="crm.filters.date_from" class="w-40" placeholder="از تاریخ" @update:model-value="changed" />
        <span class="text-slate-400 text-xs">تا</span>
        <JalaliDateField v-model="crm.filters.date_to" class="w-40" placeholder="تا تاریخ" @update:model-value="changed" />
      </template>
      <span v-if="badRange" class="text-xs text-amber-600">ترتیب تاریخ‌ها برعکس است؛ گزارش از تاریخ کوچک‌تر حساب شد</span>
    </div>

    <span class="w-px h-6 bg-slate-200 mx-1 hidden sm:block"></span>

    <!-- Only a manager has a team to filter by. For a کارشناس the API answers
         with their own rows whatever this said, so a dropdown of colleagues
         would be a control that looks like it does something and does not. -->
    <select v-if="crm.seesAll" v-model="crm.filters.owner" :class="sel" @change="changed">
      <option value="">همه کارشناسان</option>
      <option v-for="e in employees" :key="e.id" :value="e.id">{{ e.name }}</option>
    </select>

    <select v-model="crm.filters.group" :class="sel" @change="changed">
      <option value="">همه گروه‌ها</option>
      <option value="none">— بدون گروه</option>
      <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name_fa }}</option>
    </select>

    <select v-model="crm.filters.source" :class="sel" @change="changed">
      <option value="">همه منابع سرنخ</option>
      <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
    </select>

    <select v-model="crm.filters.province" :class="sel" @change="changed">
      <option value="">همه استان‌ها</option>
      <option value="none">— بدون استان</option>
      <option v-for="p in provinces" :key="p.id" :value="p.id">{{ p.name_fa }}</option>
    </select>

    <button
      v-if="active"
      class="text-xs text-red-500 hover:bg-red-50 rounded-xl px-3 py-2"
      @click="crm.reset(); changed()"
    >حذف {{ active }} فیلتر</button>

    <span class="flex-1"></span>
    <span class="text-xs text-slate-500 px-2" :title="periodText">
      گزارش: <b class="text-ink font-semibold">{{ crm.rangeLabel }}</b>
      <span v-if="periodText && crm.filters.range !== 'custom'" class="text-slate-400"> ({{ periodText }})</span>
    </span>
  </div>
</template>
