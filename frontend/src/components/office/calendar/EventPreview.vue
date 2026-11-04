<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import {
  calendarApi, KIND_LABELS, openFile, PRIORITY_LABELS, readFile, REPEAT_LABELS, RSVP_LABELS,
  type Busy, type CalendarEvent, type EventComment, type HistoryRow, type NewFile, type RsvpStatus,
} from "@/api/officeCalendar";
import type { Person } from "@/api/office";
import { apiError } from "@/components/crm/formError";
import { confirm, prompt, toast } from "@/composables/useUi";
import JalaliDateField from "@/components/JalaliDateField.vue";
import NavIcon from "@/components/NavIcon.vue";
import { jalaliLabel } from "@/utils/jalali";

/**
 * What a click on an event opens: the event, read — never the edit form.
 *
 * Tabs keep it one card rather than a wall of them:
 *  • جزئیات — time, place / link, organiser, agenda, files, who is coming and
 *    how they answered; the invitee answers here, the organiser decides on a
 *    proposed time here.
 *  • گفتگو — the meeting's own thread: replies, @mentions, edits, files.
 *  • صورت‌جلسه — the organiser records it; action items become tasks.
 *  • تاریخچه — who did what to it, and when.
 * The discussion, files, minutes and history are only for the people in the
 * meeting (`in_meeting`) — the server enforces it; this only hides the tabs.
 */
const props = defineProps<{ event: CalendarEvent; people: Person[] }>();
const emit = defineEmits<{ close: []; edit: [scope: "series" | "occurrence"]; changed: [] }>();

/** The occurrence clicked (its own start), and the event as the server has it now. */
const occ = props.event;
const ev = ref<CalendarEvent>(props.event);
async function reload() {
  const fresh = await calendarApi.event(occ.id);
  // Keep the clicked occurrence's own times; the rest from the server.
  ev.value = { ...fresh, start: occ.start, end: occ.end, series_start: fresh.start, key: occ.key };
}
onMounted(reload);

const pad = (n: number) => String(n).padStart(2, "0");
const day = (iso: string) => { const d = new Date(iso); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const stamp = (iso: string) => { const d = new Date(iso); return `${day(iso)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString("fa-IR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const whenText = (start: string, end: string, allDay = false) => {
  const a = jalaliLabel(day(start)), b = jalaliLabel(day(end));
  if (allDay) return a === b ? `${a} · تمام روز` : `${a} تا ${b}`;
  return a === b ? `${a} · ${timeOf(start)} تا ${timeOf(end)}` : `${a} ${timeOf(start)} تا ${b} ${timeOf(end)}`;
};
const atText = (iso: string) => `${jalaliLabel(day(iso))} ساعت ${timeOf(iso)}`;
const ago = (iso: string) => new Date(iso).toLocaleString("fa-IR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} مگ` : `${Math.max(1, Math.round(n / 1024))} کیلو`);

const PRIORITY_TONE: Record<string, string> = {
  normal: "bg-slate-100 text-slate-700", important: "bg-amber-100 text-amber-800", urgent: "bg-rose-100 text-rose-700",
};
const STATUS_TONE: Record<RsvpStatus, string> = {
  accepted: "text-emerald-700 bg-emerald-50", tentative: "text-amber-800 bg-amber-50", declined: "text-rose-700 bg-rose-50",
  pending: "text-slate-500 bg-slate-100", more_time: "text-violet-700 bg-violet-50", proposed: "text-sky-700 bg-sky-50",
};
const e = computed(() => ev.value);
const isOrganiser = computed(() => e.value.can_edit);
const cancelled = computed(() => !!e.value.cancelled_at);
const counts = computed(() => {
  const c: Record<RsvpStatus, number> = { accepted: 0, tentative: 0, declined: 0, pending: 0, more_time: 0, proposed: 0 };
  for (const r of e.value.responses) c[r.status]++;
  return c;
});
const overdue = computed(() => !!e.value.respond_by && new Date(e.value.respond_by) < new Date());

const tabs = computed(() => [
  { id: "details", label: "جزئیات" },
  ...(e.value.in_meeting ? [{ id: "talk", label: `گفتگو${e.value.comment_count ? ` (${e.value.comment_count.toLocaleString("fa-IR")})` : ""}` }] : []),
  ...(e.value.in_meeting && (e.value.minutes || isOrganiser.value) ? [{ id: "minutes", label: "صورت‌جلسه" }] : []),
  ...(e.value.in_meeting ? [{ id: "history", label: "تاریخچه" }] : []),
]);
const tab = ref("details");

// ---- the organiser: edit, cancel, export ----------------------------------------------
async function edit() {
  if (!e.value.repeat) return emit("edit", "series");
  const only = await confirm({ title: "ویرایش برنامه‌ی تکراری", message: "فقط همین مورد ویرایش شود؟ («انصراف» = همه‌ی تکرارها)", okText: "فقط همین مورد" });
  emit("edit", only ? "occurrence" : "series");
}
async function cancelEvent() {
  let occurrence: string | undefined;
  if (e.value.repeat) {
    const only = await confirm({ title: "لغو برنامه‌ی تکراری", message: "فقط همین مورد لغو شود؟ («انصراف» = کل سری)", okText: "فقط همین مورد", danger: true });
    if (only) occurrence = occ.start;
  }
  const reason = await prompt({ title: occurrence ? "لغو همین مورد" : "لغو جلسه", message: "علت لغو برای دعوت‌شدگان ارسال می‌شود.", placeholder: "علت لغو (اختیاری)" });
  if (reason === null) return;
  try {
    await calendarApi.cancel(e.value.id, reason, occurrence);
    toast.success("لغو شد و به دعوت‌شدگان اطلاع داده شد.");
    emit("changed");
    if (occurrence) emit("close"); else await reload();
  } catch (err) { toast.error(apiError(err)); }
}
async function ics() {
  try { await calendarApi.downloadIcs(e.value.id); } catch (err) { toast.error(apiError(err)); }
}

// ---- the invitee: answer -------------------------------------------------------------
const CHOICES: { s: RsvpStatus; label: string }[] = [
  { s: "accepted", label: "می‌آیم" }, { s: "tentative", label: "شاید" }, { s: "declined", label: "نمی‌آیم" },
  { s: "more_time", label: "مهلت می‌خواهم" }, { s: "proposed", label: "زمان دیگر پیشنهاد می‌دهم" },
];
const answer = reactive({ status: "" as RsvpStatus | "", note: "", start: "", end: "", wait: "" });
const conflicts = ref<Busy[]>([]);
function choose(s: RsvpStatus) {
  const mine = e.value.my_response;
  Object.assign(answer, {
    status: s, note: mine?.status === s ? mine.note : "",
    start: mine?.proposed_start ? stamp(mine.proposed_start) : stamp(occ.start),
    end: mine?.proposed_end ? stamp(mine.proposed_end) : stamp(occ.end),
    wait: mine?.wait_until ? stamp(mine.wait_until) : "",
  });
  conflicts.value = [];
  if (s === "accepted") calendarApi.conflicts(occ.start, occ.end, e.value.id).then((c) => (conflicts.value = c)).catch(() => {});
}
const sending = ref(false);
async function send() {
  if (!answer.status) return;
  if (answer.status === "more_time" && !answer.wait) return toast.error("بگویید تا کی پاسخ می‌دهید.");
  sending.value = true;
  try {
    await calendarApi.respond(e.value.id, {
      status: answer.status, note: answer.note,
      ...(answer.status === "proposed" ? { proposed_start: answer.start, proposed_end: answer.end } : {}),
      ...(answer.status === "more_time" ? { wait_until: answer.wait } : {}),
    });
    answer.status = "";
    toast.success("پاسخ شما برای برگزارکننده ارسال شد.");
    await reload();
    emit("changed");
  } catch (err) { toast.error(apiError(err)); } finally { sending.value = false; }
}

// ---- the organiser: a proposed time --------------------------------------------------------
async function decide(user: number, decision: "accept" | "reject") {
  if (decision === "accept" && !(await confirm({ message: "زمان جلسه به زمان پیشنهادی منتقل شود؟ از همه‌ی دعوت‌شدگان دوباره پاسخ خواسته می‌شود.", okText: "انتقال جلسه" }))) return;
  try {
    await calendarApi.decideProposal(e.value.id, user, decision);
    toast.success(decision === "accept" ? "جلسه منتقل شد و به همه اطلاع داده شد." : "پیشنهاد رد شد.");
    emit("changed");
    if (decision === "accept") emit("close"); else await reload();
  } catch (err) { toast.error(apiError(err)); }
}

// ---- files on the meeting ------------------------------------------------------------------
const meetingFiles = computed(() => e.value.attachments.filter((a) => !a.comment));
const fileInput = ref<HTMLInputElement | null>(null);
async function upload(ev_: Event) {
  const files = [...((ev_.target as HTMLInputElement).files ?? [])];
  for (const f of files) {
    try { await calendarApi.addFile(e.value.id, await readFile(f)); } catch (err) { toast.error(err instanceof Error ? err.message : apiError(err)); }
  }
  (ev_.target as HTMLInputElement).value = "";
  await reload();
}
async function download(aid: number) {
  try { openFile(await calendarApi.file(e.value.id, aid)); } catch (err) { toast.error(apiError(err)); }
}
async function removeFile(aid: number, name: string) {
  if (!(await confirm({ message: `فایل «${name}» حذف شود؟`, danger: true, okText: "حذف" }))) return;
  await calendarApi.deleteFile(e.value.id, aid);
  await reload();
}

// ---- discussion ---------------------------------------------------------------------
const comments = ref<EventComment[]>([]);
const thread = computed(() => {
  const top = comments.value.filter((c) => !c.parent);
  return top.map((c) => ({ c, replies: comments.value.filter((r) => r.parent === c.id) }));
});
watch(tab, async (t) => { if (t === "talk") comments.value = await calendarApi.comments(e.value.id); if (t === "history") history.value = await calendarApi.history(e.value.id); });
const draft = reactive({ body: "", parent: null as number | null, files: [] as NewFile[], mentions: [] as number[] });
const replyTo = computed(() => comments.value.find((c) => c.id === draft.parent));
/** @mentions: only people in the meeting — anyone else could not read it. */
const members = computed(() => {
  const ids = new Set<number>(e.value.attendees);
  const out = e.value.responses.map((r) => ({ id: r.user, name: r.name }));
  if (e.value.created_by && !ids.has(e.value.created_by)) out.unshift({ id: e.value.created_by, name: e.value.created_by_name });
  return out;
});
const mentionQ = ref<string | null>(null);
function onDraftInput(evt: Event) {
  const el = evt.target as HTMLTextAreaElement;
  const m = /@([^\s@]*)$/.exec(el.value.slice(0, el.selectionStart));
  mentionQ.value = m ? m[1] : null;
}
const mentionOptions = computed(() => mentionQ.value === null ? [] : members.value.filter((m) => m.name.includes(mentionQ.value!)).slice(0, 6));
function mention(m: { id: number; name: string }) {
  draft.body = draft.body.replace(/@([^\s@]*)$/, `@${m.name} `);
  if (!draft.mentions.includes(m.id)) draft.mentions.push(m.id);
  mentionQ.value = null;
}
async function attachToDraft(evt: Event) {
  for (const f of [...((evt.target as HTMLInputElement).files ?? [])]) {
    try { draft.files.push(await readFile(f)); } catch (err) { toast.error(err instanceof Error ? err.message : String(err)); }
  }
  (evt.target as HTMLInputElement).value = "";
}
const posting = ref(false);
async function post() {
  if (!draft.body.trim() && !draft.files.length) return;
  posting.value = true;
  try {
    // A name that was mentioned and then deleted from the text is not mentioned.
    const mentions = draft.mentions.filter((id) => draft.body.includes(`@${members.value.find((m) => m.id === id)?.name}`));
    comments.value = await calendarApi.addComment(e.value.id, { body: draft.body.trim(), parent: draft.parent, mentions, attachments: draft.files });
    Object.assign(draft, { body: "", parent: null, files: [], mentions: [] });
    ev.value = { ...ev.value, comment_count: comments.value.length };
  } catch (err) { toast.error(apiError(err)); } finally { posting.value = false; }
}
const editing = reactive({ id: 0, body: "" });
async function saveEdit() {
  try { comments.value = await calendarApi.editComment(e.value.id, editing.id, editing.body); editing.id = 0; } catch (err) { toast.error(apiError(err)); }
}
async function removeComment(c: EventComment) {
  if (!(await confirm({ message: "این نظر حذف شود؟", danger: true, okText: "حذف" }))) return;
  comments.value = await calendarApi.deleteComment(e.value.id, c.id);
}
const versions = ref<{ id: number; rows: { body: string; at: string }[] }>({ id: 0, rows: [] });
async function showVersions(c: EventComment) {
  versions.value = versions.value.id === c.id ? { id: 0, rows: [] } : { id: c.id, rows: await calendarApi.commentVersions(e.value.id, c.id) };
}
/** @name in a comment, drawn as a name rather than plain text. */
function marked(c: EventComment): { t: string; at: boolean }[] {
  const names = c.mentions.map((m) => `@${m.name}`);
  if (!names.length) return [{ t: c.body, at: false }];
  const re = new RegExp(`(${names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return c.body.split(re).filter(Boolean).map((t) => ({ t, at: names.includes(t) }));
}

// ---- minutes ------------------------------------------------------------------------
const minutes = reactive({ editing: false, text: "", items: [] as { title: string; assignee: number | null; due_on: string }[] });
function startMinutes() {
  Object.assign(minutes, { editing: true, text: e.value.minutes, items: [] });
}
async function saveMinutes() {
  try {
    await calendarApi.saveMinutes(e.value.id, minutes.text, minutes.items.filter((i) => i.title.trim()).map((i) => ({ title: i.title.trim(), assignee: i.assignee, due_on: i.due_on || null })));
    minutes.editing = false;
    toast.success("صورت‌جلسه ثبت شد.");
    await reload();
  } catch (err) { toast.error(apiError(err)); }
}

// ---- history ----------------------------------------------------------------------
const history = ref<HistoryRow[]>([]);
const ACTION_LABELS: Record<string, string> = {
  created: "ایجاد", invited: "دعوت", updated: "ویرایش", accepted: "پذیرش", tentative: "شاید", declined: "رد دعوت",
  more_time: "درخواست مهلت", proposed: "پیشنهاد زمان", proposal_accepted: "پذیرش پیشنهاد زمان",
  proposal_rejected: "رد پیشنهاد زمان", cancelled: "لغو", occurrence_cancelled: "لغو یک مورد",
  occurrence_moved: "تغییر یک مورد", commented: "نظر", comment_edited: "ویرایش نظر", comment_deleted: "حذف نظر",
  attachment: "پیوست", attachment_deleted: "حذف پیوست", minutes: "صورت‌جلسه",
};

const field = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-300";
const btn = "rounded-xl px-3 py-1.5 text-sm border border-slate-200 text-slate-700 hover:bg-slate-50 flex items-center gap-1.5";
</script>

<template>
  <div class="fixed inset-0 z-50 bg-black/30 flex items-start sm:items-center justify-center p-3 overflow-y-auto" @click.self="emit('close')">
    <article class="bg-surface rounded-2xl shadow-pop w-full max-w-2xl" role="dialog" :aria-label="e.title">
      <!-- Header -->
      <header class="flex items-start gap-3 p-5 pb-2">
        <span class="w-3.5 h-3.5 rounded mt-1.5 shrink-0" :style="{ background: e.color }"></span>
        <div class="flex-1 min-w-0 space-y-1">
          <h3 class="font-bold text-ink text-lg leading-7" :class="cancelled ? 'line-through text-slate-400' : ''">{{ e.title }}</h3>
          <p class="text-sm text-slate-600">{{ whenText(e.start, e.end, e.all_day) }}</p>
          <p v-if="e.repeat" class="text-xs text-slate-500 flex items-center gap-1"><NavIcon name="refresh" :size="13" /> {{ REPEAT_LABELS[e.repeat] }}</p>
        </div>
        <div class="flex items-center gap-0.5 shrink-0">
          <button class="w-8 h-8 rounded-full hover:bg-slate-100 text-slate-500 flex items-center justify-center" title="دریافت فایل ICS (برای Outlook / Google)" aria-label="دریافت ICS" @click="ics"><NavIcon name="download" :size="16" /></button>
          <button v-if="isOrganiser" class="w-8 h-8 rounded-full hover:bg-slate-100 text-slate-500 flex items-center justify-center" title="ویرایش" aria-label="ویرایش" @click="edit"><NavIcon name="pencil" :size="16" /></button>
          <button class="w-8 h-8 rounded-full hover:bg-slate-100 text-slate-400 flex items-center justify-center" aria-label="بستن" @click="emit('close')"><NavIcon name="close" :size="18" /></button>
        </div>
      </header>

      <p v-if="cancelled" class="mx-5 mb-2 text-sm bg-rose-50 text-rose-700 rounded-xl px-3 py-2">
        این برنامه لغو شده است{{ e.cancel_reason ? ` — علت: ${e.cancel_reason}` : "" }}.
      </p>

      <nav v-if="tabs.length > 1" class="flex gap-1 px-5 border-b border-slate-100">
        <button v-for="t in tabs" :key="t.id" class="text-sm px-3 py-2 -mb-px border-b-2 transition"
                :class="tab === t.id ? 'border-sky-500 text-ink font-medium' : 'border-transparent text-slate-500 hover:text-ink'" @click="tab = t.id">{{ t.label }}</button>
      </nav>

      <div class="p-5 space-y-4 text-sm max-h-[70vh] overflow-y-auto">
        <!-- ===== Details ===== -->
        <template v-if="tab === 'details'">
          <div class="flex flex-wrap gap-1.5 text-xs">
            <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ KIND_LABELS[e.kind] }}</span>
            <span class="rounded-full px-2 py-0.5" :class="PRIORITY_TONE[e.priority]">{{ PRIORITY_LABELS[e.priority] }}</span>
            <span class="rounded-full px-2 py-0.5 bg-slate-100">{{ e.calendar_name }}</span>
          </div>
          <div class="space-y-1.5 text-slate-600">
            <p v-if="e.location" class="flex items-center gap-2"><NavIcon name="pin" :size="15" class="text-slate-400" /> {{ e.location }}</p>
            <p v-if="e.online_link" class="flex items-center gap-2"><NavIcon name="globe" :size="15" class="text-slate-400" />
              <a :href="e.online_link" target="_blank" rel="noopener noreferrer" class="text-sky-600 hover:underline truncate ltr-nums" dir="ltr">ورود به جلسه‌ی آنلاین</a></p>
            <p class="flex items-center gap-2"><NavIcon name="users" :size="15" class="text-slate-400" /> برگزارکننده: <b class="text-ink font-medium">{{ e.created_by_name || "—" }}</b></p>
            <p v-if="e.respond_by" class="flex items-center gap-2" :class="overdue ? 'text-rose-600' : ''">
              <NavIcon name="clock" :size="15" class="text-slate-400" /> مهلت پاسخ: {{ atText(e.respond_by) }}<span v-if="overdue" class="text-xs">(گذشته)</span>
            </p>
          </div>

          <div v-if="e.description" class="space-y-1">
            <h4 class="text-xs font-medium text-slate-500">دستور جلسه</h4>
            <p class="whitespace-pre-line text-slate-700 bg-slate-50 rounded-xl p-3 leading-7">{{ e.description }}</p>
          </div>

          <!-- My answer -->
          <section v-if="e.my_response && !cancelled" class="rounded-xl border border-slate-200 p-3 space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium text-ink">پاسخ شما:</span>
              <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_TONE[e.my_response.status]">{{ RSVP_LABELS[e.my_response.status] }}</span>
              <span v-if="e.my_response.status === 'more_time' && e.my_response.wait_until" class="text-xs text-slate-500">تا {{ atText(e.my_response.wait_until) }}</span>
              <span v-if="e.my_response.status === 'proposed' && e.my_response.proposed_start" class="text-xs text-slate-500">{{ whenText(e.my_response.proposed_start, e.my_response.proposed_end || e.my_response.proposed_start) }}</span>
              <span v-if="e.my_response.proposal_decision === 'rejected'" class="text-xs text-rose-600">برگزارکننده پیشنهاد قبلی شما را نپذیرفت.</span>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <button v-for="c in CHOICES" :key="c.s" type="button" class="rounded-xl px-3 py-1.5 text-sm border transition"
                      :class="(answer.status || e.my_response.status) === c.s ? 'bg-panel text-white border-transparent' : 'border-slate-200 text-slate-700 hover:bg-slate-50'"
                      @click="choose(c.s)">{{ c.label }}</button>
            </div>
            <div v-if="answer.status" class="space-y-2 pt-1">
              <p v-if="answer.status === 'accepted' && conflicts.length" class="text-xs bg-amber-50 text-amber-800 rounded-lg px-3 py-2">
                در این زمان در تقویم خودتان این‌ها را هم دارید: {{ conflicts.map((c) => c.title).join("، ") }}
              </p>
              <div v-if="answer.status === 'more_time'" class="flex flex-wrap items-center gap-2">
                <span class="text-xs text-slate-500">تا کی پاسخ قطعی می‌دهید؟</span>
                <div class="w-60"><JalaliDateField v-model="answer.wait" with-time placeholder="مهلت درخواستی" /></div>
              </div>
              <div v-if="answer.status === 'proposed'" class="grid sm:grid-cols-2 gap-2">
                <JalaliDateField v-model="answer.start" with-time placeholder="از" />
                <JalaliDateField v-model="answer.end" with-time placeholder="تا" />
              </div>
              <textarea v-model="answer.note" rows="2" :class="field"
                        :placeholder="answer.status === 'proposed' ? 'علت پیشنهاد زمان دیگر' : 'توضیح برای برگزارکننده (اختیاری)'"></textarea>
              <div class="flex gap-2">
                <button class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm disabled:opacity-50" :disabled="sending" @click="send">ارسال پاسخ</button>
                <button class="text-sm text-slate-500 px-2" @click="answer.status = ''">انصراف</button>
              </div>
            </div>
          </section>

          <!-- Files -->
          <section v-if="e.in_meeting && (meetingFiles.length || !cancelled)" class="space-y-1.5">
            <div class="flex items-center gap-2">
              <h4 class="font-medium text-ink">پیوست‌ها</h4>
              <button v-if="!cancelled" class="mr-auto text-xs text-sky-600 hover:underline flex items-center gap-1" @click="fileInput?.click()"><NavIcon name="paperclip" :size="13" /> افزودن فایل</button>
              <input ref="fileInput" type="file" multiple class="hidden" @change="upload" />
            </div>
            <ul class="space-y-1">
              <li v-for="a in meetingFiles" :key="a.id" class="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-1.5">
                <NavIcon name="file" :size="15" class="text-slate-400" />
                <button class="flex-1 text-right truncate text-sky-700 hover:underline" @click="download(a.id)">{{ a.name }}</button>
                <span class="text-[11px] text-slate-400">{{ kb(a.size_bytes) }} · {{ a.uploaded_by_name }}</span>
                <button class="text-slate-400 hover:text-red-500" :aria-label="`حذف ${a.name}`" @click="removeFile(a.id, a.name)"><NavIcon name="trash" :size="13" /></button>
              </li>
              <li v-if="!meetingFiles.length" class="text-xs text-slate-400">فایلی پیوست نشده.</li>
            </ul>
          </section>

          <!-- Who is coming -->
          <section v-if="e.responses.length || e.guests?.length" class="space-y-2">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h4 class="font-medium text-ink">شرکت‌کنندگان</h4>
              <span class="text-xs text-slate-500">
                <template v-for="(n, st) in counts" :key="st"><span v-if="n" class="ml-2">{{ RSVP_LABELS[st] }}: {{ n.toLocaleString("fa-IR") }}</span></template>
              </span>
            </div>
            <ul class="space-y-1">
              <li v-for="r in e.responses" :key="r.user" class="rounded-lg px-2 py-1.5 hover:bg-slate-50">
                <div class="flex items-start gap-2">
                  <span class="flex-1 min-w-0">
                    <span class="text-ink">{{ r.name }}</span>
                    <span v-if="r.note" class="block text-xs text-slate-500">«{{ r.note }}»</span>
                    <span v-if="r.status === 'more_time' && r.wait_until" class="block text-xs text-violet-700">پاسخ تا {{ atText(r.wait_until) }}</span>
                    <span v-if="r.status === 'proposed' && r.proposed_start" class="block text-xs text-sky-700">زمان پیشنهادی: {{ whenText(r.proposed_start, r.proposed_end || r.proposed_start) }}</span>
                  </span>
                  <span class="text-[11px] rounded-full px-2 py-0.5 shrink-0" :class="STATUS_TONE[r.status]">{{ RSVP_LABELS[r.status] }}</span>
                </div>
                <div v-if="isOrganiser && r.status === 'proposed' && !cancelled && r.user !== e.my_response?.user" class="flex gap-1.5 mt-1.5">
                  <button class="text-xs rounded-lg px-2.5 py-1 bg-sky-500 text-white" @click="decide(r.user, 'accept')">پذیرش و انتقال جلسه</button>
                  <button class="text-xs rounded-lg px-2.5 py-1 border border-slate-200 text-slate-600" @click="decide(r.user, 'reject')">رد پیشنهاد</button>
                </div>
              </li>
              <li v-for="g in e.guests" :key="g" class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-slate-600">
                <span class="flex-1">{{ g }}</span>
                <span class="text-[11px] rounded-full px-2 py-0.5 bg-slate-100 text-slate-500">مهمان خارج از شرکت</span>
              </li>
            </ul>
          </section>

          <div v-if="isOrganiser && !cancelled" class="flex flex-wrap gap-2 pt-1 border-t border-slate-100">
            <button :class="btn" class="mt-3" @click="edit"><NavIcon name="pencil" :size="14" /> ویرایش</button>
            <button :class="btn" class="mt-3 text-rose-600" @click="cancelEvent"><NavIcon name="close" :size="14" /> {{ e.attendees.length ? "لغو جلسه" : "لغو" }}</button>
          </div>
        </template>

        <!-- ===== Discussion ===== -->
        <template v-else-if="tab === 'talk'">
          <ul class="space-y-3">
            <li v-for="t in thread" :key="t.c.id" class="space-y-2">
              <template v-for="c in [t.c, ...t.replies]" :key="c.id">
                <div class="flex gap-2" :class="c.parent ? 'mr-8' : ''">
                  <span class="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[11px] text-white"
                        :style="{ background: c.author_color || '#94a3b8' }">{{ (c.author_name || "؟").slice(0, 1) }}</span>
                  <div class="flex-1 min-w-0 bg-slate-50 rounded-xl px-3 py-2">
                    <div class="flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                      <b class="text-ink font-medium">{{ c.author_name }}</b>
                      <span>{{ ago(c.created_at) }}</span>
                      <button v-if="c.edited_at" class="text-slate-400 hover:text-sky-600" @click="showVersions(c)">(ویرایش‌شده)</button>
                      <span class="mr-auto flex items-center gap-2">
                        <button class="hover:text-sky-600" @click="draft.parent = t.c.id">پاسخ</button>
                        <button v-if="c.can_edit" class="hover:text-sky-600" @click="Object.assign(editing, { id: c.id, body: c.body })">ویرایش</button>
                        <button v-if="c.can_delete" class="hover:text-red-500" aria-label="حذف نظر" @click="removeComment(c)"><NavIcon name="trash" :size="12" /></button>
                      </span>
                    </div>
                    <div v-if="editing.id === c.id" class="mt-1 space-y-1">
                      <textarea v-model="editing.body" rows="2" :class="field"></textarea>
                      <div class="flex gap-2 text-xs"><button class="text-sky-600" @click="saveEdit">ذخیره</button><button class="text-slate-500" @click="editing.id = 0">انصراف</button></div>
                    </div>
                    <p v-else class="whitespace-pre-line mt-1 text-slate-700 leading-6">
                      <template v-for="(p, i) in marked(c)" :key="i"><span v-if="p.at" class="text-sky-700 font-medium">{{ p.t }}</span><template v-else>{{ p.t }}</template></template>
                    </p>
                    <ul v-if="versions.id === c.id" class="mt-2 space-y-1 border-t border-slate-200 pt-1.5">
                      <li v-for="(v, i) in versions.rows" :key="i" class="text-xs text-slate-500"><span class="text-slate-400">{{ ago(v.at) }}:</span> {{ v.body }}</li>
                    </ul>
                    <div v-if="c.attachments.length" class="flex flex-wrap gap-1.5 mt-1.5">
                      <button v-for="a in c.attachments" :key="a.id" class="text-xs bg-surface border border-slate-200 rounded-lg px-2 py-1 flex items-center gap-1 hover:border-sky-300" @click="download(a.id)">
                        <NavIcon name="paperclip" :size="12" /> {{ a.name }}
                      </button>
                    </div>
                  </div>
                </div>
              </template>
            </li>
            <li v-if="!thread.length" class="text-xs text-slate-400">هنوز نظری ثبت نشده. سؤال، هماهنگی یا فایل‌های جلسه را اینجا بگذارید.</li>
          </ul>

          <form class="space-y-1.5 border-t border-slate-100 pt-3" @submit.prevent="post">
            <p v-if="replyTo" class="text-xs text-slate-500 flex items-center gap-2">در پاسخ به {{ replyTo.author_name }}
              <button type="button" class="text-slate-400 hover:text-ink" aria-label="لغو پاسخ" @click="draft.parent = null"><NavIcon name="close" :size="12" /></button></p>
            <div class="relative">
              <textarea v-model="draft.body" rows="2" :class="field" placeholder="نظر، سؤال یا هماهنگی… (برای نام بردن از کسی @ بنویسید)"
                        @input="onDraftInput" @keydown.enter.exact.prevent="mentionOptions.length ? mention(mentionOptions[0]) : post()"></textarea>
              <ul v-if="mentionOptions.length" class="absolute z-10 bottom-full mb-1 w-56 bg-surface rounded-xl shadow-pop overflow-hidden text-sm">
                <li v-for="m in mentionOptions" :key="m.id"><button type="button" class="w-full text-right px-3 py-1.5 hover:bg-slate-50" @click="mention(m)">{{ m.name }}</button></li>
              </ul>
            </div>
            <div v-if="draft.files.length" class="flex flex-wrap gap-1.5">
              <span v-for="(f, i) in draft.files" :key="i" class="text-xs bg-slate-100 rounded-lg px-2 py-1 flex items-center gap-1">{{ f.name }}
                <button type="button" aria-label="حذف فایل" @click="draft.files.splice(i, 1)"><NavIcon name="close" :size="10" /></button></span>
            </div>
            <div class="flex items-center gap-2">
              <label class="text-slate-500 hover:text-sky-600 cursor-pointer flex items-center gap-1 text-xs"><NavIcon name="paperclip" :size="14" /> فایل
                <input type="file" multiple class="hidden" @change="attachToDraft" /></label>
              <button class="mr-auto bg-panel text-white rounded-xl px-4 py-1.5 text-sm disabled:opacity-50 flex items-center gap-1.5" :disabled="posting || (!draft.body.trim() && !draft.files.length)">
                <NavIcon name="send" :size="14" /> ارسال</button>
            </div>
          </form>
        </template>

        <!-- ===== Minutes ===== -->
        <template v-else-if="tab === 'minutes'">
          <template v-if="!minutes.editing">
            <p v-if="e.minutes" class="whitespace-pre-line text-slate-700 bg-slate-50 rounded-xl p-3 leading-7">{{ e.minutes }}</p>
            <p v-else class="text-xs text-slate-400">هنوز صورت‌جلسه‌ای ثبت نشده.</p>
            <p v-if="e.minutes_at" class="text-[11px] text-slate-400">آخرین ثبت: {{ ago(e.minutes_at) }}</p>
            <div v-if="e.action_items.length" class="space-y-1">
              <h4 class="font-medium text-ink">اقدامات (در «وظایف»)</h4>
              <ul class="space-y-1">
                <li v-for="a in e.action_items" :key="a.task" class="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-1.5">
                  <NavIcon :name="a.done ? 'check' : 'clipboard'" :size="14" :class="a.done ? 'text-emerald-600' : 'text-slate-400'" />
                  <span class="flex-1" :class="a.done ? 'line-through text-slate-400' : ''">{{ a.title }}</span>
                  <span class="text-xs text-slate-500">{{ a.assignee_name || "بدون مسئول" }}<template v-if="a.due_on"> · تا {{ jalaliLabel(a.due_on) }}</template></span>
                </li>
              </ul>
            </div>
            <button v-if="isOrganiser" :class="btn" @click="startMinutes"><NavIcon name="pencil" :size="14" /> {{ e.minutes ? "ویرایش صورت‌جلسه / افزودن اقدام" : "ثبت صورت‌جلسه" }}</button>
          </template>
          <template v-else>
            <textarea v-model="minutes.text" rows="6" :class="field" placeholder="خلاصه‌ی مذاکرات و تصمیم‌ها…"></textarea>
            <div class="space-y-1.5">
              <h4 class="font-medium text-ink">اقدامات تازه <span class="text-xs text-slate-400 font-normal">— هر کدام یک وظیفه در «وظایف» برای مسئولش می‌شود</span></h4>
              <div v-for="(it, i) in minutes.items" :key="i" class="grid grid-cols-[1fr_auto_auto_auto] gap-1.5 items-center">
                <input v-model="it.title" :class="field" placeholder="شرح اقدام" />
                <select v-model="it.assignee" class="bg-slate-100 rounded-xl px-2 py-2 text-sm">
                  <option :value="null">مسئول…</option>
                  <option v-for="p in people" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select>
                <div class="w-36"><JalaliDateField v-model="it.due_on" placeholder="مهلت" clearable /></div>
                <button class="text-slate-400 hover:text-red-500" aria-label="حذف اقدام" @click="minutes.items.splice(i, 1)"><NavIcon name="close" :size="14" /></button>
              </div>
              <button class="text-xs text-sky-600 hover:underline flex items-center gap-1" @click="minutes.items.push({ title: '', assignee: null, due_on: '' })"><NavIcon name="plus" :size="13" /> افزودن اقدام</button>
            </div>
            <div class="flex gap-2">
              <button class="bg-panel text-white rounded-xl px-4 py-1.5 text-sm" @click="saveMinutes">ذخیره</button>
              <button class="text-sm text-slate-500 px-2" @click="minutes.editing = false">انصراف</button>
            </div>
          </template>
        </template>

        <!-- ===== History ===== -->
        <template v-else-if="tab === 'history'">
          <ol class="relative border-r-2 border-slate-100 pr-4 space-y-3">
            <li v-for="(h, i) in history" :key="i" class="relative">
              <span class="absolute -right-[21px] top-1.5 w-2.5 h-2.5 rounded-full bg-slate-300"></span>
              <div class="text-xs text-slate-500"><b class="text-ink font-medium">{{ h.actor || "سامانه" }}</b> · {{ ACTION_LABELS[h.action] ?? h.action }} · {{ ago(h.at) }}</div>
              <p v-if="h.detail" class="text-slate-600 text-xs mt-0.5">{{ h.detail }}</p>
            </li>
            <li v-if="!history.length" class="text-xs text-slate-400">رویدادی ثبت نشده.</li>
          </ol>
        </template>
      </div>
    </article>
  </div>
</template>
