<script setup lang="ts">
import { computed } from "vue";
import type { MonthCalendar } from "@/types";

/**
 * The month laid out as a real calendar (شنبه → جمعه), with each week's days
 * banded in its own colour. This is what lets a manager see exactly which
 * days the week they are about to fill in actually covers — and lets anyone
 * confirm at a glance that the weeks cover the month with no gap or overlap.
 */
const props = defineProps<{
  calendar: MonthCalendar | null;
  selectedWeek?: number | null;
}>();
const emit = defineEmits<{ (e: "pick", seq: number): void }>();

const WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];

// Distinct but quiet bands; index by (seq - 1).
const BANDS = [
  "bg-brand-500/15 text-brand-700",
  "bg-accent-500/15 text-accent-600",
  "bg-amber-400/20 text-amber-700",
  "bg-purple-500/15 text-purple-700",
  "bg-sky-500/15 text-sky-700",
  "bg-rose-500/15 text-rose-700",
];

/** Leading blanks so day 1 lands under its real weekday column. */
const leadingBlanks = computed(() => props.calendar?.days[0]?.weekday ?? 0);

const dayCount = computed(() =>
  props.calendar?.weeks.reduce((s, w) => s + w.days, 0) ?? 0,
);
const tilesExactly = computed(
  () => !!props.calendar && dayCount.value === props.calendar.total_days,
);
</script>

<template>
  <div v-if="calendar" class="space-y-3">
    <div class="flex items-baseline justify-between gap-2 flex-wrap">
      <h4 class="font-semibold text-ink text-sm">
        تقویم {{ calendar.month_label }}
      </h4>
      <span class="text-xs ltr-nums" :class="tilesExactly ? 'text-accent-600' : 'text-red-600'">
        {{ tilesExactly ? "✓" : "✗" }}
        جمع روزهای هفته‌ها: {{ dayCount }} از {{ calendar.total_days }} روز ماه
      </span>
    </div>

    <!-- Weekday headers -->
    <div class="grid grid-cols-7 gap-1 text-center text-[11px] text-slate-400">
      <div v-for="d in WEEKDAYS" :key="d">{{ d }}</div>
    </div>

    <!-- Day grid -->
    <div class="grid grid-cols-7 gap-1">
      <div v-for="n in leadingBlanks" :key="`b${n}`"></div>
      <button
        v-for="d in calendar.days"
        :key="d.day"
        type="button"
        class="aspect-square rounded-lg text-xs font-medium flex items-center justify-center transition-all ltr-nums"
        :class="[
          d.week_seq ? BANDS[(d.week_seq - 1) % BANDS.length] : 'bg-slate-100 text-slate-400',
          selectedWeek && d.week_seq === selectedWeek ? 'ring-2 ring-ink scale-105' : '',
        ]"
        :title="`${d.day} — ${d.weekday_fa}${d.week_seq ? ` · هفته ${d.week_seq}` : ''}`"
        @click="d.week_seq && emit('pick', d.week_seq)"
      >{{ d.day }}</button>
    </div>

    <!-- Legend: which days each week holds -->
    <div v-if="calendar.weeks.length" class="flex flex-wrap gap-2 pt-1">
      <button
        v-for="w in calendar.weeks"
        :key="w.seq"
        type="button"
        class="text-[11px] rounded-lg px-2 py-1 transition-all"
        :class="[
          BANDS[(w.seq - 1) % BANDS.length],
          selectedWeek === w.seq ? 'ring-2 ring-ink' : '',
        ]"
        @click="emit('pick', w.seq)"
      >
        هفته {{ w.seq }}:
        <span class="ltr-nums">{{ w.first_day }}–{{ w.last_day }}</span>
        ({{ w.days }} روز)
      </button>
    </div>
    <p v-else class="text-xs text-slate-400">
      این ماه به هفته تقسیم نشده و به‌صورت ماهانه ثبت می‌شود.
    </p>
  </div>
</template>
