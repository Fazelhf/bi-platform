<script setup lang="ts">
/**
 * تقویم تیمیار — ددلاین‌ها، جلسات و رویدادهای هر روز روی یک ماه شمسی.
 *
 * A deadline is a task's end date; a meeting sits on its local day. Logs are
 * shown only as a count, because a calendar cell with five phone calls
 * written out in it is a calendar nobody can read.
 */
import { computed, ref } from "vue";
import { localDay, type LogEntry, type Meeting, type TeamyarTask } from "@/api/teamyar";
import {
  MONTH_NAMES, WEEKDAY_NAMES, addMonths, faDigits, firstWeekdayColumn,
  isoToJalali, jalaliLabel, jalaliToIso, monthLength, todayIso,
} from "@/utils/jalali";

const props = defineProps<{ tasks: TeamyarTask[]; meetings: Meeting[]; logs: LogEntry[] }>();
const emit = defineEmits<{
  (e: "open-task", t: TeamyarTask): void;
  (e: "open-meeting", m: Meeting): void;
}>();

const today = todayIso();
const cursor = ref(isoToJalali(today)!);
const selected = ref(today);

const cells = computed(() => {
  const { jy, jm } = cursor.value;
  const lead = firstWeekdayColumn(jy, jm);
  const out: (string | null)[] = Array(lead).fill(null);
  for (let d = 1; d <= monthLength(jy, jm); d++) out.push(jalaliToIso({ jy, jm, jd: d }));
  while (out.length % 7) out.push(null);
  return out;
});

interface DayItems { deadlines: TeamyarTask[]; starts: TeamyarTask[]; meetings: Meeting[]; logs: LogEntry[] }

const byDay = computed(() => {
  const map = new Map<string, DayItems>();
  const at = (k: string) => {
    if (!map.has(k)) map.set(k, { deadlines: [], starts: [], meetings: [], logs: [] });
    return map.get(k)!;
  };
  for (const t of props.tasks) {
    at(t.end_on).deadlines.push(t);
    if (t.start_on !== t.end_on) at(t.start_on).starts.push(t);
  }
  for (const m of props.meetings) at(localDay(m.held_at)).meetings.push(m);
  for (const l of props.logs) at(localDay(l.happened_at)).logs.push(l);
  return map;
});

const day = computed(() => byDay.value.get(selected.value));

function time(iso: string) {
  return faDigits(new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }));
}

function shift(n: number) {
  cursor.value = addMonths(cursor.value, n);
}
function goToday() {
  cursor.value = isoToJalali(today)!;
  selected.value = today;
}
</script>

<template>
  <div class="grid lg:grid-cols-[1fr_320px] gap-4">
    <div class="bg-surface rounded-card shadow-soft p-4">
      <div class="flex items-center gap-2 mb-3">
        <button class="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-500" @click="shift(-1)">›</button>
        <h3 class="font-bold text-ink min-w-[8rem] text-center">
          {{ MONTH_NAMES[cursor.jm - 1] }} {{ faDigits(cursor.jy) }}
        </h3>
        <button class="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-500" @click="shift(1)">‹</button>
        <button class="text-xs text-slate-500 hover:text-ink px-2" @click="goToday">امروز</button>
        <span class="flex-1"></span>
        <div class="hidden sm:flex items-center gap-3 text-[11px] text-slate-500">
          <span class="flex items-center gap-1"><i class="w-2 h-2 rounded-full bg-red-500"></i>ددلاین</span>
          <span class="flex items-center gap-1"><i class="w-2 h-2 rounded-full bg-violet-500"></i>جلسه</span>
          <span class="flex items-center gap-1"><i class="w-2 h-2 rounded-full bg-sky-500"></i>شروع</span>
        </div>
      </div>

      <div class="grid grid-cols-7 gap-1 text-center text-[11px] text-slate-400 mb-1">
        <div v-for="w in WEEKDAY_NAMES" :key="w">{{ w }}</div>
      </div>
      <div class="grid grid-cols-7 gap-1">
        <template v-for="(iso, i) in cells" :key="i">
          <div v-if="!iso" class="min-h-[84px]"></div>
          <button
            v-else
            class="min-h-[84px] rounded-xl p-1.5 text-right flex flex-col gap-0.5 border transition-colors overflow-hidden"
            :class="[
              iso === selected ? 'border-slate-400 bg-slate-50' : 'border-slate-100 hover:bg-slate-50',
              i % 7 === 6 ? 'bg-slate-50/50' : '',
            ]"
            @click="selected = iso"
          >
            <span
              class="text-xs w-6 h-6 flex items-center justify-center rounded-full"
              :class="iso === today ? 'bg-panel text-white font-bold' : 'text-slate-500'"
            >{{ faDigits(isoToJalali(iso)!.jd) }}</span>
            <template v-if="byDay.get(iso)">
              <span
                v-for="t in byDay.get(iso)!.deadlines.slice(0, 2)" :key="`d${t.id}`"
                class="text-[10px] leading-tight truncate rounded px-1"
                :class="t.status === 'done' ? 'bg-emerald-500/15 text-emerald-700 line-through' : 'bg-red-500/15 text-red-600'"
              >{{ t.is_milestone ? "◆ " : "" }}{{ t.title }}</span>
              <span
                v-for="m in byDay.get(iso)!.meetings.slice(0, 2)" :key="`m${m.id}`"
                class="text-[10px] leading-tight truncate rounded px-1 bg-violet-500/15 text-violet-600"
                :class="m.status === 'cancelled' ? 'line-through opacity-60' : ''"
              >{{ m.title }}</span>
              <span class="flex gap-0.5 mt-auto items-center">
                <i v-if="byDay.get(iso)!.starts.length" class="w-1.5 h-1.5 rounded-full bg-sky-500"></i>
                <span v-if="byDay.get(iso)!.logs.length" class="text-[9px] text-slate-400">
                  {{ faDigits(byDay.get(iso)!.logs.length) }} رویداد
                </span>
              </span>
            </template>
          </button>
        </template>
      </div>
    </div>

    <aside class="bg-surface rounded-card shadow-soft p-4 space-y-4 self-start">
      <h4 class="font-bold text-ink text-sm">{{ jalaliLabel(selected) }}</h4>
      <p v-if="!day" class="text-sm text-slate-400">برای این روز چیزی ثبت نشده.</p>
      <template v-else>
        <section v-if="day.deadlines.length">
          <h5 class="text-xs text-slate-400 mb-1">ددلاین‌ها</h5>
          <button
            v-for="t in day.deadlines" :key="t.id"
            class="w-full text-right text-sm py-1.5 px-2 rounded-lg hover:bg-slate-50 flex items-center gap-2"
            @click="emit('open-task', t)"
          >
            <i class="w-2 h-2 rounded-full" :class="t.status === 'done' ? 'bg-emerald-500' : 'bg-red-500'"></i>
            <span class="flex-1 truncate text-ink">{{ t.title }}</span>
            <span class="text-[11px] text-slate-400">{{ t.status_label }}</span>
          </button>
        </section>
        <section v-if="day.starts.length">
          <h5 class="text-xs text-slate-400 mb-1">شروع فعالیت</h5>
          <button
            v-for="t in day.starts" :key="t.id"
            class="w-full text-right text-sm py-1.5 px-2 rounded-lg hover:bg-slate-50 text-ink truncate"
            @click="emit('open-task', t)"
          >{{ t.title }}</button>
        </section>
        <section v-if="day.meetings.length">
          <h5 class="text-xs text-slate-400 mb-1">جلسات</h5>
          <button
            v-for="m in day.meetings" :key="m.id"
            class="w-full text-right text-sm py-1.5 px-2 rounded-lg hover:bg-slate-50 flex items-center gap-2"
            @click="emit('open-meeting', m)"
          >
            <span class="text-[11px] text-slate-400 ltr-nums">{{ time(m.held_at) }}</span>
            <span class="flex-1 truncate text-ink">{{ m.title }}</span>
            <span class="text-[11px] text-violet-500">{{ m.status_label }}</span>
          </button>
        </section>
        <section v-if="day.logs.length">
          <h5 class="text-xs text-slate-400 mb-1">رویدادها و مکالمات</h5>
          <div v-for="l in day.logs" :key="l.id" class="text-sm py-1.5 px-2">
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-slate-400 ltr-nums">{{ time(l.happened_at) }}</span>
              <span class="text-[11px] bg-slate-100 text-slate-500 rounded px-1.5">{{ l.kind_label }}</span>
              <span class="truncate text-ink">{{ l.subject }}</span>
            </div>
            <p v-if="l.counterpart" class="text-[11px] text-slate-400 mt-0.5">با {{ l.counterpart }}</p>
          </div>
        </section>
      </template>
    </aside>
  </div>
</template>
