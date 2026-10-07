<script setup lang="ts">
/**
 * ماژول‌ها — one card per module in the charter: how far it is, where the
 * plan says it should be, who owns it on both sides, and what is stuck.
 * A card opens to the activities and meetings filed under it; modules are
 * added and edited from here.
 */
import { computed, ref } from "vue";
import type { Meeting, ModuleCard, TeamyarTask } from "@/api/teamyar";
import { faDigits, jalaliLabel } from "@/utils/jalali";

const props = defineProps<{
  modules: ModuleCard[];
  general: ModuleCard | null;
  tasks: TeamyarTask[];
  meetings: Meeting[];
}>();
const emit = defineEmits<{
  (e: "task", t: TeamyarTask): void;
  (e: "meeting", m: Meeting): void;
  (e: "edit", id: number | null): void;
}>();

const fa = (n: number | null | undefined) => faDigits(n ?? 0);
const open = ref<number | "general" | null>(null);
const cards = computed(() => [...props.modules, ...(props.general ? [props.general] : [])]);

const CHIP: Record<string, string> = {
  todo: "bg-slate-100 text-slate-500",
  doing: "bg-blue-500/15 text-blue-600",
  blocked: "bg-red-500/15 text-red-600",
  done: "bg-emerald-500/15 text-emerald-600",
};
const BAR: Record<string, string> = {
  todo: "bg-slate-400", doing: "bg-blue-500", blocked: "bg-red-500", done: "bg-emerald-500",
};

function inModule(key: number | "general") {
  const mine = (m: number | null) => (key === "general" ? m === null : m === key);
  return {
    tasks: props.tasks.filter((t) => mine(t.module)),
    meetings: props.meetings.filter((m) => mine(m.module))
      .sort((a, b) => b.held_at.localeCompare(a.held_at)),
  };
}
function gap(c: ModuleCard) {
  return Math.round(c.progress - c.planned);
}
function hours(min: number) {
  return faDigits(Math.round((min / 60) * 10) / 10);
}
</script>

<template>
  <div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
    <div
      v-for="c in cards" :key="c.key"
      class="bg-surface rounded-card shadow-soft p-4 flex flex-col"
      :class="open === c.key ? 'sm:col-span-2 xl:col-span-3' : ''"
    >
      <button class="text-right w-full" @click="open = open === c.key ? null : c.key">
        <div class="flex items-start gap-2">
          <h3 class="flex-1 min-w-0 font-bold text-ink text-sm">{{ c.label }}</h3>
          <span
            v-if="c.key !== 'general'" role="button" title="ویرایش ماژول"
            class="text-slate-400 hover:text-ink text-xs px-1" @click.stop="emit('edit', c.key as number)"
          >✎</span>
          <span v-if="c.key !== 'general' || c.task_count" class="text-[10px] rounded px-1.5 py-0.5 shrink-0" :class="CHIP[c.status]">
            {{ c.task_count ? c.status_label : "تعریف نشده" }}
          </span>
        </div>
        <p v-if="c.specialist" class="text-[11px] text-slate-400 mt-0.5 truncate">
          <template v-if="c.owner">{{ c.owner }} · </template>{{ c.specialist }} (تیمیار)
        </p>
        <p v-else-if="c.key === 'general'" class="text-[11px] text-slate-400 mt-0.5">کارهای بدون ماژول (سرور، سایت، جلسات کلی) — در پیشرفت کل حساب نمی‌شود</p>
        <p v-else-if="c.owner" class="text-[11px] text-slate-400 mt-0.5 truncate">{{ c.owner }}</p>
        <p v-if="c.key !== 'general' && !c.in_scope" class="text-[11px] text-amber-600 mt-0.5">در پیشرفت کل حساب نمی‌شود</p>

        <div class="flex items-baseline gap-2 mt-3">
          <span class="text-2xl font-bold text-ink">{{ fa(c.progress) }}٪</span>
          <span v-if="c.key !== 'general'" class="text-[11px] text-slate-400">
            طبق برنامه {{ fa(c.planned) }}٪
            <span v-if="c.task_count" :class="gap(c) < 0 ? 'text-red-500' : 'text-emerald-600'">
              ({{ gap(c) < 0 ? "عقب" : "جلو" }} {{ fa(Math.abs(gap(c))) }})
            </span>
          </span>
        </div>
        <div class="relative h-2 bg-slate-100 rounded-full overflow-hidden mt-1">
          <div class="h-full rounded-full transition-all" :class="BAR[c.status]" :style="{ width: `${c.progress}%` }"></div>
          <div
            v-if="c.key !== 'general'"
            class="absolute top-0 bottom-0 w-0.5 bg-ink/60" :style="{ right: `${c.planned}%` }"
            title="جایی که طبق برنامه باید باشد"
          ></div>
        </div>

        <div class="flex flex-wrap gap-x-3 gap-y-1 mt-3 text-[11px] text-slate-500">
          <span>📋 {{ fa(c.done_count) }}/{{ fa(c.task_count) }} فعالیت</span>
          <span>👥 {{ fa(c.meetings_held) }} جلسه<template v-if="c.meeting_minutes"> · {{ hours(c.meeting_minutes) }} ساعت</template></span>
          <span v-if="c.avg_rating" class="text-amber-500">★ {{ fa(c.avg_rating) }}</span>
          <span v-if="c.overdue_count" class="text-red-500">⏰ {{ fa(c.overdue_count) }} عقب‌افتاده</span>
          <span v-if="c.blocked_count" class="text-red-500">⛔ {{ fa(c.blocked_count) }} متوقف</span>
          <span v-if="c.open_issues" class="text-amber-600">⚠ {{ fa(c.open_issues) }} مشکل باز</span>
        </div>
        <p v-if="c.next_deadline" class="text-[11px] text-slate-500 mt-1 truncate">
          ددلاین بعدی: {{ c.next_deadline.title }} · {{ jalaliLabel(c.next_deadline.end_on) }}
        </p>
        <p v-else-if="!c.task_count && c.start_on" class="text-[11px] text-slate-400 mt-1">
          طبق برنامه از {{ jalaliLabel(c.start_on) }} — هنوز فعالیتی ثبت نشده
        </p>
      </button>

      <div v-if="open === c.key" class="grid md:grid-cols-2 gap-4 mt-4 pt-3 border-t border-slate-100">
        <div>
          <h4 class="text-xs font-bold text-slate-500 mb-1">فعالیت‌ها</h4>
          <p v-if="!inModule(c.key).tasks.length" class="text-sm text-slate-400">فعالیتی در این ماژول نیست.</p>
          <button
            v-for="t in inModule(c.key).tasks" :key="t.id"
            class="w-full text-right py-2 border-b border-slate-50 last:border-0"
            @click="emit('task', t)"
          >
            <div class="flex items-center gap-2">
              <span class="flex-1 text-sm text-ink truncate" :class="t.status === 'done' ? 'line-through text-slate-400' : ''">
                {{ t.is_milestone ? "◆ " : "" }}{{ t.title }}
              </span>
              <span class="text-[10px] rounded px-1.5 shrink-0" :class="CHIP[t.status]">{{ t.status_label }}</span>
              <span class="text-[11px] text-slate-400 w-9 text-left">{{ fa(t.status === "done" ? 100 : t.progress) }}٪</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-0.5 truncate">
              {{ t.owner || "—" }} · تا {{ jalaliLabel(t.end_on) }}
              <span v-if="t.is_overdue" class="text-red-500"> · عقب</span>
            </p>
          </button>
        </div>
        <div>
          <h4 class="text-xs font-bold text-slate-500 mb-1">جلسات</h4>
          <p v-if="!inModule(c.key).meetings.length" class="text-sm text-slate-400">جلسه‌ای ثبت نشده.</p>
          <button
            v-for="m in inModule(c.key).meetings" :key="m.id"
            class="w-full text-right py-2 border-b border-slate-50 last:border-0"
            @click="emit('meeting', m)"
          >
            <div class="flex items-center gap-2">
              <span class="flex-1 text-sm text-ink truncate">{{ m.title }}</span>
              <span v-if="m.rating" class="text-[11px] text-amber-500">{{ "★".repeat(m.rating) }}</span>
            </div>
            <p class="text-[11px] text-slate-400 mt-0.5">
              {{ jalaliLabel(m.held_at) }} · {{ m.status_label }} · {{ fa(m.duration_min) }} دقیقه
            </p>
          </button>
        </div>
      </div>
    </div>
    <button
      class="rounded-card border-2 border-dashed border-slate-200 p-4 min-h-[140px] text-sm text-slate-500
             hover:text-ink hover:border-slate-300 flex flex-col items-center justify-center gap-1"
      @click="emit('edit', null)"
    >
      <span class="text-2xl leading-none">+</span>
      ماژول جدید
      <span class="text-[11px] text-slate-400">مثلاً پست و پیامک، حقوق و دستمزد</span>
    </button>
  </div>
</template>
