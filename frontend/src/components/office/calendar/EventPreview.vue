<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  calendarApi, KIND_LABELS, PRIORITY_LABELS, REPEAT_LABELS,
  type CalendarEvent, type EventComment, type RsvpStatus,
} from "@/api/officeCalendar";
import { apiError } from "@/components/crm/formError";
import { confirm, toast } from "@/composables/useUi";
import JalaliDateField from "@/components/JalaliDateField.vue";
import NavIcon from "@/components/NavIcon.vue";
import { jalaliLabel } from "@/utils/jalali";

/**
 * What a click on an event opens: the event as an invitation, read, not
 * edited. Its time and place, who organised it, who is coming and who is
 * not, the invitee's own answer (accept / maybe / decline, a note, another
 * time that would suit), and the discussion under it. Editing is a button
 * here, for whoever may edit.
 */
const props = defineProps<{ event: CalendarEvent }>();
const emit = defineEmits<{ close: []; edit: []; changed: [] }>();

const e = computed(() => props.event);
const pad = (n: number) => String(n).padStart(2, "0");
const day = (iso: string) => { const d = new Date(iso); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit" });
const whenText = (start: string, end: string, allDay = false) => {
  const a = jalaliLabel(day(start)), b = jalaliLabel(day(end));
  if (allDay) return a === b ? `${a} · تمام روز` : `${a} تا ${b}`;
  return a === b ? `${a} · ${timeOf(start)} تا ${timeOf(end)}` : `${a} ${timeOf(start)} تا ${b} ${timeOf(end)}`;
};
const PRIORITY_TONE: Record<string, string> = {
  normal: "bg-slate-100 text-slate-700", important: "bg-amber-100 text-amber-800", urgent: "bg-rose-100 text-rose-700",
};
const STATUS_TONE: Record<RsvpStatus, string> = {
  accepted: "text-emerald-700 bg-emerald-50", tentative: "text-amber-800 bg-amber-50",
  declined: "text-rose-700 bg-rose-50", pending: "text-slate-500 bg-slate-100",
};
const STATUS_LABEL: Record<RsvpStatus, string> = {
  accepted: "می‌آید", tentative: "شاید", declined: "نمی‌آید", pending: "بی‌پاسخ",
};
const ANSWER_LABEL: Record<RsvpStatus, string> = {
  accepted: "می‌آیم", tentative: "شاید / بعداً اعلام می‌کنم", declined: "نمی‌آیم", pending: "",
};
/** Kept here so the caller's own answer shows in the list the moment it is sent. */
const responses = ref([...e.value.responses]);
const counts = computed(() => {
  const c = { accepted: 0, tentative: 0, declined: 0, pending: 0 };
  for (const r of responses.value) c[r.status]++;
  return c;
});
const overdue = computed(() => !!e.value.respond_by && new Date(e.value.respond_by) < new Date());

// ---- my answer -----------------------------------------------------------------
const mine = ref(e.value.my_response);
const answer = reactive({ open: false, status: "" as RsvpStatus | "", note: "", propose: false, start: "", end: "" });
function choose(s: RsvpStatus) {
  Object.assign(answer, { open: true, status: s, note: mine.value?.status === s ? mine.value.note : "", propose: false });
  const d = new Date(e.value.start);
  answer.start = `${day(e.value.start)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const en = new Date(e.value.end);
  answer.end = `${day(e.value.end)}T${pad(en.getHours())}:${pad(en.getMinutes())}`;
}
const sending = ref(false);
async function send() {
  if (!answer.status) return;
  sending.value = true;
  try {
    mine.value = await calendarApi.respond(e.value.id, {
      status: answer.status as RsvpStatus, note: answer.note,
      ...(answer.propose && answer.start ? { proposed_start: answer.start, proposed_end: answer.end || undefined } : {}),
    });
    responses.value = responses.value.map((r) => (r.user === mine.value!.user ? mine.value! : r));
    answer.open = false;
    toast.success("پاسخ شما برای برگزارکننده ارسال شد.");
    emit("changed");
  } catch (err) {
    toast.error(apiError(err));
  } finally {
    sending.value = false;
  }
}

// ---- discussion ------------------------------------------------------------------
const comments = ref<EventComment[]>([]);
const draft = ref("");
const posting = ref(false);
onMounted(async () => { comments.value = await calendarApi.comments(e.value.id); });
async function post() {
  if (!draft.value.trim()) return;
  posting.value = true;
  try {
    comments.value = await calendarApi.addComment(e.value.id, draft.value.trim());
    draft.value = "";
  } catch (err) {
    toast.error(apiError(err));
  } finally {
    posting.value = false;
  }
}
async function removeComment(c: EventComment) {
  if (!(await confirm({ message: "این نظر حذف شود؟", danger: true, okText: "حذف" }))) return;
  await calendarApi.deleteComment(e.value.id, c.id);
  comments.value = comments.value.filter((x) => x.id !== c.id);
}
const ago = (iso: string) => new Date(iso).toLocaleString("fa-IR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
const field = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-300";
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/30 flex items-start sm:items-center justify-center p-3 overflow-y-auto" @click.self="emit('close')">
    <article class="bg-surface rounded-2xl shadow-pop w-full max-w-xl" role="dialog" :aria-label="e.title">
      <!-- Header -->
      <header class="flex items-start gap-3 p-5 pb-3">
        <span class="w-3.5 h-3.5 rounded mt-1.5 shrink-0" :style="{ background: e.color }"></span>
        <div class="flex-1 min-w-0 space-y-1">
          <h3 class="font-bold text-ink text-lg leading-7">{{ e.title }}</h3>
          <p class="text-sm text-slate-600">{{ whenText(e.start, e.end, e.all_day) }}</p>
          <p v-if="e.repeat" class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="refresh" :size="13" /> {{ REPEAT_LABELS[e.repeat] }}</p>
        </div>
        <div class="flex items-center gap-1 shrink-0">
          <button v-if="e.can_edit" class="w-8 h-8 rounded-full hover:bg-slate-100 text-slate-500 flex items-center justify-center" title="ویرایش" aria-label="ویرایش" @click="emit('edit')"><NavIcon name="pencil" :size="16" /></button>
          <button class="w-8 h-8 rounded-full hover:bg-slate-100 text-slate-400 flex items-center justify-center" aria-label="بستن" @click="emit('close')"><NavIcon name="close" :size="18" /></button>
        </div>
      </header>

      <div class="px-5 pb-5 space-y-4 text-sm">
        <div class="flex flex-wrap gap-1.5 text-xs">
          <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ KIND_LABELS[e.kind] }}</span>
          <span class="rounded-full px-2 py-0.5" :class="PRIORITY_TONE[e.priority]">{{ PRIORITY_LABELS[e.priority] }}</span>
          <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ e.calendar_name }}</span>
        </div>

        <div class="space-y-1.5 text-slate-600">
          <p v-if="e.location" class="flex items-center gap-2"><NavIcon name="pin" :size="15" class="text-slate-400" /> {{ e.location }}</p>
          <p class="flex items-center gap-2"><NavIcon name="users" :size="15" class="text-slate-400" /> برگزارکننده: <b class="text-ink font-medium">{{ e.created_by_name || "—" }}</b></p>
          <p v-if="e.respond_by" class="flex items-center gap-2" :class="overdue ? 'text-rose-600' : ''">
            <NavIcon name="clock" :size="15" class="text-slate-400" /> مهلت پاسخ: {{ jalaliLabel(day(e.respond_by)) }} ساعت {{ timeOf(e.respond_by) }}
            <span v-if="overdue" class="text-xs">(گذشته)</span>
          </p>
        </div>

        <p v-if="e.description" class="whitespace-pre-line text-slate-700 bg-slate-50 rounded-xl p-3 leading-7">{{ e.description }}</p>

        <!-- My answer -->
        <section v-if="mine" class="rounded-xl border border-slate-200 p-3 space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-medium text-ink">پاسخ شما:</span>
            <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_TONE[mine.status]">{{ mine.status_display }}</span>
            <span v-if="mine.proposed_start" class="text-xs text-slate-500">پیشنهاد: {{ whenText(mine.proposed_start, mine.proposed_end || mine.proposed_start) }}</span>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button v-for="s in (['accepted', 'tentative', 'declined'] as RsvpStatus[])" :key="s" type="button"
                    class="rounded-xl px-4 py-1.5 text-sm border transition"
                    :class="(answer.open ? answer.status : mine.status) === s ? 'bg-panel text-white border-transparent' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
                    @click="choose(s)">{{ ANSWER_LABEL[s] }}</button>
          </div>
          <div v-if="answer.open" class="space-y-2 pt-1">
            <textarea v-model="answer.note" rows="2" :class="field" placeholder="توضیح برای برگزارکننده (اختیاری) — مثلاً دلیل، یا تا کی پاسخ قطعی می‌دهید"></textarea>
            <label class="flex items-center gap-2 text-xs text-slate-600"><input v-model="answer.propose" type="checkbox" /> زمان دیگری پیشنهاد می‌دهم</label>
            <div v-if="answer.propose" class="grid sm:grid-cols-2 gap-2">
              <JalaliDateField v-model="answer.start" with-time placeholder="از" />
              <JalaliDateField v-model="answer.end" with-time placeholder="تا" />
            </div>
            <div class="flex gap-2">
              <button class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm disabled:opacity-50" :disabled="sending" @click="send">ارسال پاسخ</button>
              <button class="text-sm text-slate-500 px-2" @click="answer.open = false">انصراف</button>
            </div>
          </div>
        </section>

        <!-- Who is coming -->
        <section v-if="responses.length || e.guests?.length" class="space-y-2">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h4 class="font-medium text-ink">شرکت‌کنندگان</h4>
            <span class="text-xs text-slate-500">
              {{ counts.accepted.toLocaleString("fa-IR") }} می‌آیند ·
              {{ counts.tentative.toLocaleString("fa-IR") }} شاید ·
              {{ counts.declined.toLocaleString("fa-IR") }} نمی‌آیند ·
              {{ counts.pending.toLocaleString("fa-IR") }} بی‌پاسخ
            </span>
          </div>
          <ul class="space-y-1">
            <li v-for="r in responses" :key="r.user" class="flex items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50">
              <span class="flex-1 min-w-0">
                <span class="text-ink">{{ r.name }}</span>
                <span v-if="r.note" class="block text-xs text-slate-500">«{{ r.note }}»</span>
                <span v-if="r.proposed_start" class="block text-xs text-sky-700">زمان پیشنهادی: {{ whenText(r.proposed_start, r.proposed_end || r.proposed_start) }}</span>
              </span>
              <span class="text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="STATUS_TONE[r.status]">{{ STATUS_LABEL[r.status] }}</span>
            </li>
            <li v-for="g in e.guests" :key="g" class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-slate-600">
              <span class="flex-1">{{ g }}</span>
              <span class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500">مهمان خارج از شرکت</span>
            </li>
          </ul>
        </section>

        <!-- Discussion -->
        <section class="space-y-2 border-t border-slate-100 pt-3">
          <h4 class="font-medium text-ink flex items-center gap-1.5"><NavIcon name="chat" :size="15" class="text-slate-400" /> گفتگو درباره‌ی این برنامه</h4>
          <ul class="space-y-2 max-h-64 overflow-y-auto">
            <li v-for="c in comments" :key="c.id" class="bg-slate-50 rounded-xl px-3 py-2">
              <div class="flex items-center gap-2 text-xs text-slate-500">
                <b class="text-ink font-medium">{{ c.author_name }}</b>
                <span>{{ ago(c.created_at) }}</span>
                <button v-if="c.can_delete" class="mr-auto text-slate-400 hover:text-red-500" aria-label="حذف نظر" @click="removeComment(c)"><NavIcon name="trash" :size="13" /></button>
              </div>
              <p class="whitespace-pre-line mt-1 text-slate-700">{{ c.body }}</p>
            </li>
            <li v-if="!comments.length" class="text-xs text-slate-400">هنوز نظری ثبت نشده.</li>
          </ul>
          <form class="flex gap-2 items-end" @submit.prevent="post">
            <textarea v-model="draft" rows="1" :class="field" placeholder="نظر، سؤال یا هماهنگی…" @keydown.enter.exact.prevent="post"></textarea>
            <button class="bg-panel text-white rounded-xl px-3 py-2 disabled:opacity-50" :disabled="posting || !draft.trim()" aria-label="ارسال نظر"><NavIcon name="send" :size="16" /></button>
          </form>
        </section>
      </div>
    </article>
  </div>
</template>
