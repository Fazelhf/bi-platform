<script setup lang="ts">
import { computed } from "vue";
import type { MonthProgress, WeekSlot } from "@/types";

/**
 * The strip under a month picker: one dot per week, how many are in, the date
 * the data runs to, and a warning while the month is still open.
 *
 * Clicking a dot drills into that week; clicking the month label goes back to
 * the whole month.
 */
const props = defineProps<{ progress: MonthProgress | null; selected?: number | null }>();
const emit = defineEmits<{ (e: "pick", periodId: number | null): void }>();

const STATE_DOT: Record<WeekSlot["state"], string> = {
  approved: "bg-accent-500",
  submitted: "bg-amber-400",
  draft: "bg-brand-500/60",
  empty: "bg-slate-300",
};
const STATE_FA: Record<WeekSlot["state"], string> = {
  approved: "تأیید‌شده",
  submitted: "منتظر تأیید",
  draft: "پیش‌نویس",
  empty: "وارد نشده",
};

// Only a split month has a meaningful strip; a plain monthly period has one
// "week" that is the month itself.
const show = computed(() => (props.progress?.weeks.length ?? 0) > 1);

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("fa-IR", { day: "numeric", month: "long" })
    .format(new Date(iso));
}
</script>

<template>
  <div v-if="show && progress" class="flex items-center gap-3 flex-wrap text-xs">
    <div class="flex items-center gap-1.5">
      <button
        v-for="w in progress.weeks"
        :key="w.id"
        class="w-3 h-3 rounded-full transition-transform hover:scale-125"
        :class="[STATE_DOT[w.state], selected === w.id ? 'ring-2 ring-offset-1 ring-ink' : '']"
        :title="`${w.label} · ${w.days} روز · ${STATE_FA[w.state]}`"
        @click="emit('pick', selected === w.id ? null : w.id)"
      ></button>
    </div>

    <span class="text-slate-500 ltr-nums">
      {{ progress.entered }} از {{ progress.total }} هفته
    </span>

    <span v-if="progress.as_of" class="text-slate-500">
      · داده تا {{ fmtDate(progress.as_of) }}
    </span>

    <span
      v-if="!progress.complete"
      class="text-amber-600 bg-amber-50 rounded-full px-2 py-0.5"
      title="بعضی هفته‌های این ماه هنوز ثبت نشده‌اند"
    >⚠ ماه کامل نشده</span>
    <span v-else class="text-accent-600">✓ ماه کامل است</span>

    <button
      v-if="selected"
      class="text-brand-600 hover:underline"
      @click="emit('pick', null)"
    >نمایش کل ماه</button>
  </div>
</template>
