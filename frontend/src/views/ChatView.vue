<script setup lang="ts">
/**
 * گفتگو — direct threads and groups, told apart by a tab.
 *
 * The list is three tabs (همه / گروه‌ها / اعضا) with saved messages pinned on
 * top of each. The thread reads like a messenger, because that is what people
 * compare it to the moment they open it:
 *
 *   • Every message has its actions on it — reply, react, copy, and for your
 *     own: edit (48 hours, the server decides) and delete for everyone. They
 *     appear on hover, or on tap where there is no hover.
 *   • A withdrawn message stays as «این پیام حذف شد» so replies to it still
 *     point at something and the thread keeps its shape.
 *   • Days are separated, runs from one person are grouped, and a direct
 *     message you sent shows whether it has been read.
 *   • The composer grows with the text: Enter sends, Shift+Enter breaks the
 *     line, Esc leaves a reply or an edit.
 *
 * Polling refreshes the open thread every few seconds, so edits, deletions
 * and reactions from the other side arrive without a reload — and it only
 * scrolls you down if you were already at the bottom.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { socialApi, type TeamMember } from "@/api/social";
import { workApi, type ChatGroup, type ChatMessageRow } from "@/api/officeWork";
import { officeApi, type Person } from "@/api/office";
import { useAuthStore } from "@/stores/auth";
import { apiError, faDate } from "@/utils/adminFormat";
import { confirm, toast } from "@/composables/useUi";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import FormModal from "@/components/crm/FormModal.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import NavIcon from "@/components/NavIcon.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

type Tab = "all" | "groups" | "people";
const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "همه" },
  { key: "groups", label: "گروه‌ها" },
  { key: "people", label: "اعضا" },
];
const tab = ref<Tab>("all");
const search = ref("");

const contacts = ref<TeamMember[]>([]);
const groups = ref<ChatGroup[]>([]);
const people = ref<Person[]>([]);
const unread = ref<Record<string, number>>({});
const activeId = ref<number | null>(null);
const activeGroupId = ref<number | null>(null);
const messages = ref<ChatMessageRow[]>([]);
const threadLoading = ref(false);
const myId = ref<number | null>(null);

// -- composer state ----------------------------------------------------
const draft = ref("");
const replyTo = ref<ChatMessageRow | null>(null);
const editing = ref<ChatMessageRow | null>(null);
const pending = ref<{ name: string; mime: string; content: string; size: number }[]>([]);
const MAX_BYTES = 5 * 1024 * 1024;
const sending = ref(false);
const sendError = ref("");
const composerEl = ref<HTMLTextAreaElement | null>(null);

// -- per-message UI ----------------------------------------------------
/** The reactions people actually send, in the order they reach for them. */
const EMOJI = ["👍", "❤️", "😂", "😮", "😢", "🙏", "👏", "🔥", "✅", "👌", "💯", "🎉"];
/** Which message has its action bar pinned open (tap on touch screens). */
const menuFor = ref<number | null>(null);
const pickerFor = ref<number | null>(null);
const moreFor = ref<number | null>(null);
const flashId = ref<number | null>(null);

const threadEl = ref<HTMLElement | null>(null);
let timer: number | undefined;

// ======================================================================
// Lookups
// ======================================================================
const active = computed(() => contacts.value.find((c) => c.id === activeId.value) || null);
const activeGroup = computed(
  () => groups.value.find((g) => g.id === activeGroupId.value) || null,
);
const isSavedOpen = computed(() => !!myId.value && activeId.value === myId.value);
/**
 * Whether a conversation is open at all. `contacts` excludes you, so the
 * saved-messages thread has to be counted on its own.
 */
const hasThread = computed(
  () => !!active.value || !!activeGroup.value || isSavedOpen.value,
);

/** Names for «who reacted», from both directories. */
const nameOf = computed(() => {
  const map: Record<number, string> = {};
  for (const p of people.value) map[p.id] = p.name;
  for (const c of contacts.value) map[c.id] = c.name;
  if (myId.value) map[myId.value] = "شما";
  return map;
});

const isMine = (m: ChatMessageRow) => m.sender === myId.value;

/** Direct-thread metadata from the overview payload. */
const directMeta = ref<Record<number, { last_at: string; last_message: string }>>({});

type ListRow = {
  key: string; id: number; kind: "group" | "direct";
  title: string; sub: string; at: string; unread: number; person?: TeamMember;
};

const allThreads = computed<ListRow[]>(() => {
  const rows: ListRow[] = [];
  for (const g of groups.value) {
    rows.push({
      key: `g${g.id}`, id: g.id, kind: "group", title: g.title,
      sub: g.last_message || `${g.member_count} عضو`,
      at: g.last_at ?? "", unread: g.unread,
    });
  }
  for (const c of contacts.value) {
    const meta = directMeta.value[c.id];
    if (!meta || c.id === myId.value) continue;
    rows.push({
      key: `d${c.id}`, id: c.id, kind: "direct", title: c.name,
      sub: meta.last_message, at: meta.last_at,
      unread: unread.value[c.id] ?? 0, person: c,
    });
  }
  return rows.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
});

const groupRows = computed<ListRow[]>(() =>
  groups.value.map((g) => ({
    key: `g${g.id}`, id: g.id, kind: "group" as const, title: g.title,
    sub: g.last_message || `${g.member_count} عضو`, at: g.last_at ?? "", unread: g.unread,
  })),
);

const peopleRows = computed<ListRow[]>(() =>
  contacts.value.map((c) => ({
    key: `p${c.id}`, id: c.id, kind: "direct" as const, title: c.name,
    sub: c.job_title_fa || c.department_label || "", at: directMeta.value[c.id]?.last_at ?? "",
    unread: unread.value[c.id] ?? 0, person: c,
  })),
);

const visibleRows = computed(() => {
  const source = tab.value === "all" ? allThreads.value
    : tab.value === "groups" ? groupRows.value : peopleRows.value;
  const q = search.value.trim();
  return q ? source.filter((r) => r.title.includes(q) || r.sub.includes(q)) : source;
});

function isRowActive(row: ListRow): boolean {
  return row.kind === "group" ? activeGroupId.value === row.id : activeId.value === row.id;
}

// ======================================================================
// Time formatting
// ======================================================================
const timeFmt = new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" });
function hhmm(iso: string): string {
  return timeFmt.format(new Date(iso));
}
function dayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}
function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86_400_000);
  if (dayKey(d.toISOString()) === dayKey(today.toISOString())) return "امروز";
  if (dayKey(d.toISOString()) === dayKey(yesterday.toISOString())) return "دیروز";
  return faDate(iso);
}
/** List-row stamp: the time today, the date before that. */
function listStamp(iso: string): string {
  if (!iso) return "";
  return dayKey(iso) === dayKey(new Date().toISOString()) ? hhmm(iso) : faDate(iso);
}

/**
 * The thread with day separators and «runs»: consecutive messages from one
 * person within five minutes share one name and one avatar.
 */
const timeline = computed(() => {
  const out: (
    | { type: "day"; key: string; label: string }
    | { type: "msg"; key: string; m: ChatMessageRow; first: boolean; last: boolean }
  )[] = [];
  const list = messages.value;
  for (let i = 0; i < list.length; i++) {
    const m = list[i];
    const prev = list[i - 1];
    const next = list[i + 1];
    if (!prev || dayKey(prev.created_at) !== dayKey(m.created_at)) {
      out.push({ type: "day", key: `day-${m.id}`, label: dayLabel(m.created_at) });
    }
    const joins = (a?: ChatMessageRow, b?: ChatMessageRow) =>
      !!a && !!b && a.sender === b.sender && dayKey(a.created_at) === dayKey(b.created_at)
      && Math.abs(+new Date(b.created_at) - +new Date(a.created_at)) < 5 * 60_000;
    out.push({
      type: "msg", key: `m-${m.id}`, m,
      first: !joins(prev, m), last: !joins(m, next),
    });
  }
  return out;
});

// ======================================================================
// Loading
// ======================================================================
async function loadContacts() {
  const team = await socialApi.team();
  contacts.value = team.filter((m) => m.username !== auth.me?.username);
  myId.value = auth.me?.id ?? team.find((m) => m.username === auth.me?.username)?.id ?? null;
  unread.value = (await socialApi.unreadMessages()).by_sender;
}

async function loadGroups() {
  try {
    const data = await workApi.chatOverview();
    groups.value = data.groups;
    directMeta.value = Object.fromEntries(
      data.direct.map((d) => [d.user.id, { last_at: d.last_at, last_message: d.last_message }]),
    );
  } catch {
    // The office app may not be reachable for this account; direct chat
    // must keep working regardless.
    groups.value = [];
  }
}

function resetComposer() {
  draft.value = "";
  replyTo.value = null;
  editing.value = null;
  pending.value = [];
  sendError.value = "";
  menuFor.value = pickerFor.value = moreFor.value = null;
}

async function openThread(id: number) {
  if (activeId.value !== id) resetComposer();
  activeGroupId.value = null;
  activeId.value = id;
  infoOpen.value = false;
  router.replace({ name: "chat", query: { with: String(id) } });
  threadLoading.value = true;
  try {
    messages.value = await socialApi.conversation(id);
    unread.value = { ...unread.value, [id]: 0 };
  } finally {
    threadLoading.value = false;
  }
  await scrollDown();
  composerEl.value?.focus();
}

async function openGroup(id: number) {
  if (activeGroupId.value !== id) resetComposer();
  activeId.value = null;
  activeGroupId.value = id;
  router.replace({ name: "chat", query: { group: String(id) } });
  threadLoading.value = true;
  try {
    const data = await workApi.group(id);
    messages.value = data.messages;
    const row = groups.value.find((g) => g.id === id);
    if (row) Object.assign(row, { ...data, messages: undefined, unread: 0 });
  } finally {
    threadLoading.value = false;
  }
  await scrollDown();
  composerEl.value?.focus();
}

function openRow(row: ListRow) {
  return row.kind === "group" ? openGroup(row.id) : openThread(row.id);
}

function closeThread() {
  activeId.value = null;
  activeGroupId.value = null;
  infoOpen.value = false;
  router.replace({ name: "chat", query: {} });
}

function nearBottom(): boolean {
  const el = threadEl.value;
  return !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80;
}

async function scrollDown() {
  await nextTick();
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight;
}

async function poll() {
  if (document.hidden) return;
  const stick = nearBottom();
  const before = messages.value.length;
  try {
    if (activeGroupId.value) {
      messages.value = (await workApi.group(activeGroupId.value)).messages;
    } else if (activeId.value) {
      messages.value = await socialApi.conversation(activeId.value);
    }
    unread.value = (await socialApi.unreadMessages()).by_sender;
    await loadGroups();
  } catch {
    return; // a missed poll is not worth a banner; the next one retries
  }
  if (stick && messages.value.length !== before) await scrollDown();
}

// ======================================================================
// Composer
// ======================================================================
function pickFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  for (const file of Array.from(input.files ?? [])) {
    if (file.size > MAX_BYTES) {
      sendError.value = `حجم «${file.name}» بیش از ۵ مگابایت است.`;
      continue;
    }
    const reader = new FileReader();
    reader.onload = () => pending.value.push({
      name: file.name, mime: file.type,
      content: String(reader.result), size: file.size,
    });
    reader.readAsDataURL(file);
  }
  input.value = "";
}

function autoGrow() {
  const el = composerEl.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
}
watch(draft, () => nextTick(autoGrow));

function onComposerKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  } else if (e.key === "Escape") {
    if (editing.value) cancelEdit();
    else replyTo.value = null;
  }
}

const canSend = computed(
  () => !sending.value && (!!draft.value.trim() || (!editing.value && pending.value.length > 0)),
);

async function submit() {
  if (!canSend.value) return;
  if (editing.value) return saveEdit();

  const body = draft.value.trim();
  const files = pending.value.map(({ name, mime, content }) => ({ name, mime, content }));
  const parent = replyTo.value?.id ?? null;
  sending.value = true;
  sendError.value = "";
  try {
    let row: ChatMessageRow | null = null;
    if (activeGroupId.value) {
      row = await workApi.postToGroup(activeGroupId.value, body, {
        reply_to: parent, attachments: files,
      });
    } else if (activeId.value) {
      row = await socialApi.sendMessage(activeId.value, body, {
        reply_to: parent, attachments: files,
      });
    }
    if (row) messages.value.push(row);
    // Cleared only once it is safely sent — a failed send keeps your words.
    draft.value = "";
    pending.value = [];
    replyTo.value = null;
    await scrollDown();
    loadGroups();
  } catch (e) {
    sendError.value = apiError(e, "ارسال نشد. دوباره تلاش کنید.");
  } finally {
    sending.value = false;
    composerEl.value?.focus();
  }
}

// ======================================================================
// Message actions
// ======================================================================
function patchRow(row: ChatMessageRow) {
  const i = messages.value.findIndex((x) => x.id === row.id);
  if (i !== -1) messages.value[i] = { ...messages.value[i], ...row };
}

function closeMenus() {
  menuFor.value = pickerFor.value = moreFor.value = null;
}

function startReply(m: ChatMessageRow) {
  closeMenus();
  editing.value = null;
  replyTo.value = m;
  composerEl.value?.focus();
}

function startEdit(m: ChatMessageRow) {
  closeMenus();
  replyTo.value = null;
  editing.value = m;
  draft.value = m.body;
  nextTick(() => {
    composerEl.value?.focus();
    autoGrow();
  });
}

function cancelEdit() {
  editing.value = null;
  draft.value = "";
}

async function saveEdit() {
  const m = editing.value!;
  const body = draft.value.trim();
  if (body === m.body) return cancelEdit();
  sending.value = true;
  sendError.value = "";
  try {
    patchRow(await workApi.editMessage(m.id, body));
    cancelEdit();
  } catch (e) {
    sendError.value = apiError(e, "ویرایش انجام نشد.");
  } finally {
    sending.value = false;
  }
}

async function remove(m: ChatMessageRow) {
  closeMenus();
  const ok = await confirm({
    title: "حذف پیام",
    message: "این پیام برای همه حذف می‌شود و به‌جایش «این پیام حذف شد» می‌ماند.",
    danger: true,
  });
  if (!ok) return;
  try {
    patchRow(await workApi.deleteMessage(m.id));
    if (editing.value?.id === m.id) cancelEdit();
    if (replyTo.value?.id === m.id) replyTo.value = null;
    loadGroups();
  } catch (e) {
    toast.error(apiError(e, "حذف انجام نشد."));
  }
}

async function copy(m: ChatMessageRow) {
  closeMenus();
  try {
    await navigator.clipboard.writeText(m.body);
    toast.success("متن پیام کپی شد.");
  } catch {
    toast.error("کپی انجام نشد.");
  }
}

/** Optimistic, so a tap feels like a tap; the server's summary wins after. */
async function react(m: ChatMessageRow, emoji: string) {
  closeMenus();
  const before = m.reactions.map((r) => ({ ...r, who: [...r.who] }));
  const me = myId.value ?? 0;
  const hit = m.reactions.find((r) => r.emoji === emoji);
  if (hit?.mine) {
    hit.count -= 1;
    hit.mine = false;
    hit.who = hit.who.filter((id) => id !== me);
    if (!hit.count) m.reactions = m.reactions.filter((r) => r !== hit);
  } else if (hit) {
    hit.count += 1;
    hit.mine = true;
    hit.who.push(me);
  } else {
    m.reactions.push({ emoji, count: 1, mine: true, who: [me] });
  }
  try {
    const { reactions } = await workApi.react(m.id, emoji);
    m.reactions = reactions;
  } catch (e) {
    m.reactions = before;
    toast.error(apiError(e, "واکنش ثبت نشد."));
  }
}

function reactors(r: { who: number[] }): string {
  return r.who.map((id) => nameOf.value[id] ?? "").filter(Boolean).join("، ");
}

/** Jump to the quoted message and flash it, so «کدام سؤال؟» has an answer. */
async function jumpTo(id: number) {
  const el = threadEl.value?.querySelector<HTMLElement>(`[data-msg="${id}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  flashId.value = id;
  window.setTimeout(() => { if (flashId.value === id) flashId.value = null; }, 1400);
}

/** Tapping a bubble pins its actions open — the touch-screen stand-in for hover. */
function toggleMenu(m: ChatMessageRow, e: MouseEvent) {
  if (m.deleted) return;
  if ((e.target as HTMLElement).closest("button, a, img")) return;
  if (window.getSelection()?.toString()) return;
  menuFor.value = menuFor.value === m.id ? null : m.id;
  pickerFor.value = moreFor.value = null;
}

// -- attachments -------------------------------------------------------
async function fetchFile(m: ChatMessageRow, attId: number) {
  return activeGroupId.value
    ? workApi.chatAttachment(m.id, attId)
    : socialApi.directAttachment(attId);
}

async function openAttachment(m: ChatMessageRow, attId: number, name: string) {
  try {
    const file = await fetchFile(m, attId);
    const a = document.createElement("a");
    a.href = file.content;
    a.download = name;
    a.click();
  } catch (e) {
    toast.error(apiError(e, "دریافت فایل انجام نشد."));
  }
}

/** Images are shown, not downloaded — that is the point of sending one. */
const previews = ref<Record<number, string>>({});
async function loadPreview(m: ChatMessageRow, att: { id: number; is_image: boolean }) {
  if (!att.is_image || previews.value[att.id]) return;
  try {
    previews.value[att.id] = (await fetchFile(m, att.id)).content;
  } catch { /* the chip still downloads it */ }
}

function kb(bytes: number): string {
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

// ======================================================================
// Groups
// ======================================================================
const makingGroup = ref(false);
const groupForm = ref({ title: "", members: [] as number[] });
const savingGroup = ref(false);
const groupError = ref("");

async function createGroup() {
  if (!groupForm.value.title.trim()) {
    groupError.value = "نام گروه را بنویسید.";
    return;
  }
  savingGroup.value = true;
  groupError.value = "";
  try {
    const g = await workApi.createGroup(groupForm.value.title, groupForm.value.members);
    makingGroup.value = false;
    groupForm.value = { title: "", members: [] };
    await loadGroups();
    await openGroup(g.id);
  } catch (e) {
    groupError.value = apiError(e, "ساخت گروه انجام نشد.");
  } finally {
    savingGroup.value = false;
  }
}

/** The group's side panel: name, members, leave. */
const infoOpen = ref(false);
const renaming = ref(false);
const newTitle = ref("");
const adding = ref<number[]>([]);
const groupBusy = ref(false);

const memberIds = computed(() => (activeGroup.value?.members ?? []).map((p) => p.id));

async function groupAction(fn: () => Promise<ChatGroup | void>, done?: string) {
  groupBusy.value = true;
  try {
    const row = await fn();
    if (row && activeGroup.value) Object.assign(activeGroup.value, row);
    if (done) toast.success(done);
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    groupBusy.value = false;
  }
}

function saveTitle() {
  const title = newTitle.value.trim();
  if (!title || !activeGroup.value) return;
  renaming.value = false;
  return groupAction(() => workApi.renameGroup(activeGroup.value!.id, title), "نام گروه تغییر کرد.");
}

function addMembers() {
  if (!adding.value.length || !activeGroup.value) return;
  const ids = adding.value;
  adding.value = [];
  return groupAction(() => workApi.groupMembers(activeGroup.value!.id, ids), "اعضا اضافه شدند.");
}

async function removeMember(p: Person) {
  if (!activeGroup.value) return;
  const ok = await confirm({ message: `«${p.name}» از گروه حذف شود؟`, danger: true });
  if (ok) await groupAction(() => workApi.groupMembers(activeGroup.value!.id, [], [p.id]));
}

async function leave() {
  if (!activeGroup.value) return;
  const ok = await confirm({
    title: "ترک گروه",
    message: `از گروه «${activeGroup.value.title}» خارج می‌شوید و دیگر پیام‌هایش را نمی‌بینید.`,
    danger: true,
  });
  if (!ok) return;
  try {
    await workApi.leaveGroup(activeGroup.value.id);
    closeThread();
    await loadGroups();
    toast.success("از گروه خارج شدید.");
  } catch (e) {
    toast.error(apiError(e));
  }
}

function groupInitial(title: string): string {
  return title.trim().slice(0, 1) || "گ";
}

// ======================================================================
onMounted(async () => {
  officeApi.people().then((d) => (people.value = d.people)).catch(() => {});
  await Promise.all([loadContacts(), loadGroups()]);
  const withId = Number(route.query.with);
  const groupId = Number(route.query.group);
  if (groupId) await openGroup(groupId);
  else if (withId) await openThread(withId);
  timer = window.setInterval(poll, 6_000);
  document.addEventListener("click", outside);
});
onBeforeUnmount(() => {
  window.clearInterval(timer);
  document.removeEventListener("click", outside);
});

/** A click anywhere outside a message's menus closes them. */
function outside(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest("[data-msg]")) closeMenus();
}

watch(() => route.query.with, (v) => { if (v && Number(v) !== activeId.value) openThread(Number(v)); });
watch(() => route.query.group, (v) => { if (v && Number(v) !== activeGroupId.value) openGroup(Number(v)); });
</script>

<template>
  <div class="office-card overflow-hidden flex relative" style="height: calc(100vh - 8rem)">
    <!-- ================= List ================= -->
    <aside
      class="w-full md:w-80 border-l border-slate-100 flex-col shrink-0"
      :class="!hasThread ? 'flex' : 'hidden md:flex'"
    >
      <div class="px-3 pt-3 pb-2 space-y-2 border-b border-slate-100">
        <div class="flex items-center justify-between">
          <h2 class="font-bold text-ink">گفتگو</h2>
          <button
            class="office-icon-btn"
            aria-label="گروه جدید"
            title="گروه جدید"
            @click="makingGroup = true"
          ><NavIcon name="user-plus" :size="18" /></button>
        </div>
        <label class="office-search block">
          <NavIcon name="search" :size="16" />
          <input v-model="search" class="office-input" placeholder="جستجوی گفتگو یا همکار…" />
        </label>
        <div class="office-seg w-full">
          <button
            v-for="t in TABS" :key="t.key"
            class="flex-1 justify-center"
            :class="{ 'is-active': tab === t.key }"
            @click="tab = t.key"
          >{{ t.label }}</button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto py-1">
        <!-- Saved messages: pinned above every tab. -->
        <button
          v-if="!search"
          class="office-row w-full flex items-center gap-3 px-3 py-2.5 text-right"
          :class="{ 'is-selected': isSavedOpen }"
          @click="myId && openThread(myId)"
        >
          <span class="w-11 h-11 rounded-full bg-panel text-white grid place-items-center shrink-0">
            <NavIcon name="bookmark" :size="18" />
          </span>
          <span class="flex-1 min-w-0">
            <span class="block text-sm font-semibold text-ink truncate">پیام‌های ذخیره‌شده</span>
            <span class="block text-xs text-slate-400 truncate">یادداشت‌ها و لینک‌های خودتان</span>
          </span>
        </button>

        <p v-if="!visibleRows.length" class="text-center text-slate-400 text-xs py-10 px-6 leading-6">
          <template v-if="search">چیزی با «{{ search }}» پیدا نشد.</template>
          <template v-else-if="tab === 'groups'">هنوز گروهی ندارید. با دکمه‌ی بالا یک گروه بسازید.</template>
          <template v-else>هنوز گفتگویی شروع نشده. از «اعضا» یک نفر را انتخاب کنید.</template>
        </p>

        <button
          v-for="row in visibleRows" :key="row.key"
          class="office-row w-full flex items-center gap-3 px-3 py-2.5 text-right"
          :class="{ 'is-selected': isRowActive(row) }"
          @click="openRow(row)"
        >
          <span
            v-if="row.kind === 'group'"
            class="w-11 h-11 rounded-full grid place-items-center shrink-0 text-white font-bold"
            style="background: rgb(var(--office-hue-chat))"
          >{{ groupInitial(row.title) }}</span>
          <UserAvatar
            v-else-if="row.person"
            :name="row.person.name" :initials="row.person.initials" :image="row.person.avatar_image"
            :color="row.person.avatar_color" :online="row.person.is_online" :size="44"
          />
          <span class="flex-1 min-w-0">
            <span class="flex items-baseline gap-2">
              <span
                class="flex-1 text-sm truncate"
                :class="row.unread ? 'font-bold text-ink' : 'font-medium text-ink'"
              >{{ row.title }}</span>
              <span v-if="row.at && tab !== 'people'" class="text-[11px] text-slate-400 ltr-nums shrink-0">
                {{ listStamp(row.at) }}
              </span>
            </span>
            <span class="flex items-center gap-2 mt-0.5">
              <span class="flex-1 text-xs truncate" :class="row.unread ? 'text-slate-600' : 'text-slate-400'">
                {{ row.sub }}
              </span>
              <span v-if="row.unread" class="office-count is-alert ltr-nums shrink-0">{{ row.unread }}</span>
            </span>
          </span>
        </button>
      </div>
    </aside>

    <!-- ================= Thread ================= -->
    <section class="flex-1 flex-col min-w-0" :class="!hasThread ? 'hidden md:flex' : 'flex'">
      <template v-if="hasThread">
        <header class="flex items-center gap-3 px-3 sm:px-4 h-16 border-b border-slate-100 shrink-0">
          <button class="office-icon-btn md:hidden" aria-label="بازگشت به فهرست" @click="closeThread">
            <NavIcon name="arrow-right" :size="18" />
          </button>

          <template v-if="isSavedOpen">
            <span class="w-10 h-10 rounded-full bg-panel text-white grid place-items-center shrink-0">
              <NavIcon name="bookmark" :size="17" />
            </span>
            <div class="min-w-0">
              <p class="font-semibold text-ink truncate">پیام‌های ذخیره‌شده</p>
              <p class="text-xs text-slate-400">فقط خودتان می‌بینید</p>
            </div>
          </template>
          <template v-else-if="activeGroup">
            <span
              class="w-10 h-10 rounded-full grid place-items-center shrink-0 text-white font-bold"
              style="background: rgb(var(--office-hue-chat))"
            >{{ groupInitial(activeGroup.title) }}</span>
            <button class="min-w-0 text-right" @click="infoOpen = !infoOpen">
              <p class="font-semibold text-ink truncate">{{ activeGroup.title }}</p>
              <p class="text-xs text-slate-400 truncate">
                <span class="ltr-nums">{{ activeGroup.member_count }}</span> عضو
                <template v-if="activeGroup.members?.length">
                  — {{ activeGroup.members.slice(0, 4).map((p) => p.name).join("، ") }}
                </template>
              </p>
            </button>
          </template>
          <template v-else-if="active">
            <UserAvatar
              :name="active.name" :initials="active.initials" :image="active.avatar_image"
              :color="active.avatar_color" :online="active.is_online" :size="40"
            />
            <div class="min-w-0">
              <p class="font-semibold text-ink truncate">{{ active.name }}</p>
              <p class="text-xs" :class="active.is_online ? 'text-accent-600' : 'text-slate-400'">
                {{ active.is_online ? "آنلاین" : (active.job_title_fa || "آفلاین") }}
              </p>
            </div>
          </template>

          <span class="flex-1"></span>
          <button
            v-if="activeGroup"
            class="office-icon-btn"
            :class="{ 'is-on': infoOpen }"
            aria-label="اطلاعات گروه"
            title="اطلاعات گروه"
            @click="infoOpen = !infoOpen"
          ><NavIcon name="info" :size="19" /></button>
        </header>

        <div class="flex-1 flex min-h-0">
          <div class="flex-1 flex flex-col min-w-0">
            <!-- Messages -->
            <div ref="threadEl" class="flex-1 overflow-y-auto px-3 sm:px-5 py-4 bg-canvas/40">
              <div v-if="threadLoading && !messages.length" class="space-y-3">
                <div v-for="i in 5" :key="i" class="flex" :class="i % 2 ? 'justify-start' : 'justify-end'">
                  <div class="h-10 rounded-2xl bg-slate-200/70 animate-pulse" :style="{ width: `${30 + i * 8}%` }"></div>
                </div>
              </div>

              <div
                v-else-if="!messages.length"
                class="h-full flex flex-col items-center justify-center gap-2 text-slate-400 text-sm"
              >
                <NavIcon name="chat" :size="32" />
                <p>هنوز پیامی رد و بدل نشده. اولین پیام را بفرستید.</p>
              </div>

              <template v-for="item in timeline" :key="item.key">
                <div v-if="item.type === 'day'" class="flex justify-center my-3">
                  <span class="text-[11px] text-slate-500 bg-surface/90 shadow-soft rounded-full px-3 py-1">
                    {{ item.label }}
                  </span>
                </div>

                <div
                  v-else
                  :data-msg="item.m.id"
                  class="group/msg flex items-end gap-2"
                  :class="[
                    isMine(item.m) ? 'flex-row' : 'flex-row-reverse',
                    item.first ? 'mt-3' : 'mt-0.5',
                  ]"
                >
                  <!-- Avatar slot: in a group, once per run, at its foot. -->
                  <div v-if="activeGroup && !isMine(item.m)" class="w-8 shrink-0">
                    <UserAvatar v-if="item.last" :user="item.m.sender_detail" :size="32" />
                  </div>

                  <div
                    class="relative max-w-[78%] sm:max-w-[68%] flex flex-col"
                    :class="isMine(item.m) ? 'items-start' : 'items-end'"
                  >
                    <!-- Bubble -->
                    <div
                      class="rounded-2xl px-3.5 py-2 text-sm transition-shadow"
                      :class="[
                        item.m.deleted
                          ? 'bg-transparent border border-dashed border-slate-300 text-slate-400'
                          : isMine(item.m) ? 'bg-panel text-white' : 'bg-surface shadow-soft text-ink',
                        isMine(item.m) && item.last ? 'rounded-tr-md' : '',
                        !isMine(item.m) && item.last ? 'rounded-tl-md' : '',
                        flashId === item.m.id ? 'ring-2 ring-amber-400' : '',
                      ]"
                      @click="toggleMenu(item.m, $event)"
                    >
                      <p
                        v-if="activeGroup && !isMine(item.m) && item.first && !item.m.deleted"
                        class="text-[11px] font-semibold mb-0.5"
                        :style="{ color: item.m.sender_detail.avatar_color || undefined }"
                      >{{ item.m.sender_detail.name }}</p>

                      <template v-if="item.m.deleted">
                        <p class="flex items-center gap-1.5 italic text-xs">
                          <NavIcon name="trash" :size="13" /> این پیام حذف شد
                        </p>
                      </template>

                      <template v-else>
                        <button
                          v-if="item.m.reply_to"
                          class="block w-full text-right rounded-lg px-2 py-1 mb-1.5 text-[11px] border-r-2"
                          :class="isMine(item.m)
                            ? 'bg-white/10 border-white/50'
                            : 'bg-slate-100 border-slate-400'"
                          @click.stop="jumpTo(item.m.reply_to.id)"
                        >
                          <span class="font-semibold block">{{ item.m.reply_to.sender_name }}</span>
                          <span class="block truncate opacity-80">{{ item.m.reply_to.body || "پیوست" }}</span>
                        </button>

                        <p v-if="item.m.body" class="leading-6 whitespace-pre-wrap break-words">{{ item.m.body }}</p>

                        <div v-if="item.m.attachments?.length" class="space-y-1.5" :class="item.m.body ? 'mt-1.5' : ''">
                          <template v-for="a in item.m.attachments" :key="a.id">
                            <img
                              v-if="a.is_image"
                              :src="previews[a.id]"
                              class="rounded-xl max-h-60 min-h-[4rem] min-w-[6rem] bg-black/5 cursor-zoom-in"
                              :alt="a.name"
                              @vue:mounted="loadPreview(item.m, a)"
                              @click.stop="openAttachment(item.m, a.id, a.name)"
                            />
                            <button
                              v-else
                              class="flex items-center gap-2 rounded-xl px-2.5 py-2 text-xs w-full min-w-[12rem]"
                              :class="isMine(item.m) ? 'bg-white/10 hover:bg-white/15' : 'bg-slate-100 hover:bg-slate-200'"
                              @click.stop="openAttachment(item.m, a.id, a.name)"
                            >
                              <NavIcon name="file" :size="18" class="shrink-0" />
                              <span class="truncate flex-1 text-right">{{ a.name }}</span>
                              <span class="opacity-60 ltr-nums shrink-0">{{ kb(a.size_bytes) }}</span>
                              <NavIcon name="download" :size="15" class="shrink-0 opacity-70" />
                            </button>
                          </template>
                        </div>
                      </template>

                      <p
                        class="flex items-center gap-1 justify-end text-[10px] mt-0.5"
                        :class="item.m.deleted ? '' : 'opacity-60'"
                      >
                        <span v-if="item.m.edited_at && !item.m.deleted">ویرایش‌شده ·</span>
                        <span class="ltr-nums">{{ hhmm(item.m.created_at) }}</span>
                        <NavIcon
                          v-if="isMine(item.m) && !activeGroup && !isSavedOpen && !item.m.deleted"
                          :name="item.m.is_read ? 'check-double' : 'check'"
                          :size="13"
                          :title="item.m.is_read ? 'خوانده شد' : 'ارسال شد'"
                        />
                      </p>
                    </div>

                    <!-- Reactions, grouped. Yours is outlined; hover says who. -->
                    <div v-if="item.m.reactions?.length" class="flex flex-wrap gap-1 mt-1">
                      <button
                        v-for="r in item.m.reactions" :key="r.emoji"
                        class="text-xs rounded-full px-2 py-0.5 border flex items-center gap-1 transition-colors"
                        :class="r.mine
                          ? 'border-[rgb(var(--office-hue-chat))] bg-[rgb(var(--office-hue-chat)/0.1)]'
                          : 'border-slate-200 bg-surface hover:bg-slate-50'"
                        :title="reactors(r)"
                        @click="react(item.m, r.emoji)"
                      >
                        <span>{{ r.emoji }}</span>
                        <span class="ltr-nums text-slate-500">{{ r.count }}</span>
                      </button>
                    </div>

                    <!-- Action bar: on hover, or pinned open by a tap. -->
                    <div
                      v-if="!item.m.deleted"
                      class="absolute top-0 z-10 flex items-center gap-0.5 bg-surface shadow-pop rounded-xl p-0.5
                             transition-opacity"
                      :class="[
                        isMine(item.m) ? 'left-full ml-1' : 'right-full mr-1',
                        menuFor === item.m.id || pickerFor === item.m.id || moreFor === item.m.id
                          ? 'opacity-100'
                          : 'opacity-0 pointer-events-none group-hover/msg:opacity-100 group-hover/msg:pointer-events-auto',
                      ]"
                    >
                      <button
                        class="office-icon-btn !w-7 !h-7"
                        aria-label="واکنش" title="واکنش"
                        @click.stop="pickerFor = pickerFor === item.m.id ? null : item.m.id; moreFor = null"
                      ><NavIcon name="smile" :size="16" /></button>
                      <button
                        class="office-icon-btn !w-7 !h-7"
                        aria-label="پاسخ" title="پاسخ"
                        @click.stop="startReply(item.m)"
                      ><NavIcon name="reply" :size="16" /></button>
                      <button
                        class="office-icon-btn !w-7 !h-7"
                        aria-label="بیشتر" title="بیشتر"
                        @click.stop="moreFor = moreFor === item.m.id ? null : item.m.id; pickerFor = null"
                      ><NavIcon name="more" :size="16" /></button>

                      <!-- Emoji picker -->
                      <div
                        v-if="pickerFor === item.m.id"
                        class="absolute top-full mt-1 grid grid-cols-6 gap-0.5 bg-surface shadow-pop rounded-xl p-1.5 w-max"
                        :class="isMine(item.m) ? 'left-0' : 'right-0'"
                      >
                        <button
                          v-for="e in EMOJI" :key="e"
                          class="w-8 h-8 rounded-lg text-lg leading-none hover:bg-slate-100 transition-transform hover:scale-110"
                          @click.stop="react(item.m, e)"
                        >{{ e }}</button>
                      </div>

                      <!-- More menu -->
                      <div
                        v-if="moreFor === item.m.id"
                        class="absolute top-full mt-1 bg-surface shadow-pop rounded-xl p-1 w-40 text-sm"
                        :class="isMine(item.m) ? 'left-0' : 'right-0'"
                      >
                        <button
                          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-slate-100 text-right"
                          @click.stop="startReply(item.m)"
                        ><NavIcon name="reply" :size="15" /> پاسخ</button>
                        <button
                          v-if="item.m.body"
                          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-slate-100 text-right"
                          @click.stop="copy(item.m)"
                        ><NavIcon name="copy" :size="15" /> کپی متن</button>
                        <button
                          v-if="item.m.can_edit"
                          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg hover:bg-slate-100 text-right"
                          @click.stop="startEdit(item.m)"
                        ><NavIcon name="pencil" :size="15" /> ویرایش</button>
                        <button
                          v-if="isMine(item.m)"
                          class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg office-btn-danger text-right"
                          @click.stop="remove(item.m)"
                        ><NavIcon name="trash" :size="15" /> حذف برای همه</button>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
            </div>

            <!-- Composer -->
            <div class="border-t border-slate-100 bg-surface shrink-0">
              <div
                v-if="replyTo || editing"
                class="mx-3 mt-2 flex items-start gap-2 rounded-xl bg-slate-50 px-3 py-2 text-xs border-r-2"
                :style="{ borderColor: 'rgb(var(--office-hue-chat))' }"
              >
                <NavIcon :name="editing ? 'pencil' : 'reply'" :size="15" class="mt-0.5 shrink-0 text-slate-500" />
                <span class="flex-1 min-w-0">
                  <span class="font-semibold text-ink block">
                    {{ editing ? "ویرایش پیام" : `پاسخ به ${replyTo!.sender_detail?.name}` }}
                  </span>
                  <span class="block truncate text-slate-500">
                    {{ (editing ?? replyTo)!.body || "پیوست" }}
                  </span>
                </span>
                <button
                  class="office-icon-btn !w-6 !h-6"
                  aria-label="لغو"
                  @click="editing ? cancelEdit() : (replyTo = null)"
                ><NavIcon name="close" :size="14" /></button>
              </div>

              <div v-if="pending.length && !editing" class="px-3 pt-2 flex flex-wrap gap-1.5">
                <span
                  v-for="(f, i) in pending" :key="i"
                  class="flex items-center gap-1.5 bg-slate-100 rounded-lg pr-2 pl-1 py-1 text-[11px] text-slate-600"
                >
                  <NavIcon name="paperclip" :size="13" />
                  <span class="truncate max-w-[10rem]">{{ f.name }}</span>
                  <span class="text-slate-400 ltr-nums">{{ kb(f.size) }}</span>
                  <button class="office-icon-btn !w-5 !h-5" aria-label="حذف فایل" @click="pending.splice(i, 1)">
                    <NavIcon name="close" :size="12" />
                  </button>
                </span>
              </div>

              <p v-if="sendError" class="px-4 pt-2 text-xs text-red-600">{{ sendError }}</p>

              <form class="p-2.5 flex items-end gap-2" @submit.prevent="submit">
                <label
                  v-if="!editing"
                  class="office-icon-btn !w-10 !h-10 cursor-pointer shrink-0"
                  title="پیوست فایل"
                  aria-label="پیوست فایل"
                >
                  <NavIcon name="paperclip" :size="20" />
                  <input type="file" multiple class="hidden" @change="pickFiles" />
                </label>
                <textarea
                  ref="composerEl"
                  v-model="draft"
                  rows="1"
                  :placeholder="editing ? 'متن ویرایش‌شده…' : 'پیام…'"
                  class="flex-1 resize-none bg-slate-100 rounded-2xl px-4 py-2.5 text-sm text-ink leading-6
                         outline-none focus:ring-2 focus:ring-[rgb(var(--office-hue-chat)/0.4)] max-h-40"
                  @keydown="onComposerKey"
                ></textarea>
                <button
                  type="submit"
                  class="w-10 h-10 rounded-full text-white grid place-items-center shrink-0 transition-opacity
                         disabled:opacity-40 disabled:cursor-not-allowed"
                  style="background: rgb(var(--office-hue-chat))"
                  :disabled="!canSend"
                  :aria-label="editing ? 'ذخیره' : 'ارسال'"
                >
                  <NavIcon :name="editing ? 'check' : 'send'" :size="18" class="-scale-x-100" />
                </button>
              </form>
              <p class="hidden sm:block px-4 pb-2 -mt-1 text-[10px] text-slate-400">
                Enter ارسال · Shift+Enter خط جدید · Esc لغو
              </p>
            </div>
          </div>

          <!-- Group info panel -->
          <aside
            v-if="infoOpen && activeGroup"
            class="absolute inset-0 z-20 bg-surface md:static md:z-auto md:w-72 md:border-r border-slate-100
                   flex flex-col shrink-0"
          >
            <div class="office-card-head">
              <span class="office-card-title flex-1">اطلاعات گروه</span>
              <button class="office-icon-btn" aria-label="بستن" @click="infoOpen = false">
                <NavIcon name="close" :size="16" />
              </button>
            </div>

            <div class="flex-1 overflow-y-auto p-4 space-y-5">
              <div class="flex flex-col items-center gap-2 text-center">
                <span
                  class="w-16 h-16 rounded-full grid place-items-center text-white text-2xl font-bold"
                  style="background: rgb(var(--office-hue-chat))"
                >{{ groupInitial(activeGroup.title) }}</span>
                <template v-if="!renaming">
                  <p class="font-bold text-ink">{{ activeGroup.title }}</p>
                  <button
                    class="office-btn-ghost !h-7 text-xs"
                    @click="renaming = true; newTitle = activeGroup.title"
                  ><NavIcon name="pencil" :size="13" /> تغییر نام</button>
                </template>
                <form v-else class="w-full flex gap-1.5" @submit.prevent="saveTitle">
                  <input v-model="newTitle" class="office-input" maxlength="120" />
                  <button class="office-btn-subtle" :disabled="groupBusy || !newTitle.trim()">ذخیره</button>
                </form>
              </div>

              <div>
                <p class="office-label">
                  اعضا · <span class="ltr-nums">{{ activeGroup.member_count }}</span>
                </p>
                <ul class="space-y-1">
                  <li
                    v-for="p in activeGroup.members ?? []" :key="p.id"
                    class="group/m flex items-center gap-2.5 rounded-lg px-1.5 py-1.5 hover:bg-slate-50"
                  >
                    <UserAvatar :user="p" :size="30" />
                    <span class="flex-1 min-w-0">
                      <span class="block text-sm text-ink truncate">
                        {{ p.id === myId ? "شما" : p.name }}
                      </span>
                      <span v-if="p.job_title_fa" class="block text-[11px] text-slate-400 truncate">
                        {{ p.job_title_fa }}
                      </span>
                    </span>
                    <button
                      v-if="p.id !== myId"
                      class="office-icon-btn !w-7 !h-7 opacity-0 group-hover/m:opacity-100 focus:opacity-100"
                      :aria-label="`حذف ${p.name}`"
                      :disabled="groupBusy"
                      @click="removeMember(p)"
                    ><NavIcon name="close" :size="14" /></button>
                  </li>
                </ul>
              </div>

              <div class="space-y-2">
                <p class="office-label">افزودن عضو</p>
                <PeoplePicker v-model="adding" :people="people" :taken="memberIds" placeholder="جستجوی همکار…" />
                <button
                  class="office-btn-subtle w-full"
                  :disabled="groupBusy || !adding.length"
                  @click="addMembers"
                ><NavIcon name="user-plus" :size="15" /> افزودن</button>
              </div>
            </div>

            <div class="p-3 border-t border-slate-100">
              <button class="office-btn-ghost office-btn-danger w-full" @click="leave">
                <NavIcon name="logout" :size="15" /> ترک گروه
              </button>
            </div>
          </aside>
        </div>
      </template>

      <div v-else class="flex-1 flex flex-col items-center justify-center gap-3 text-slate-400 text-sm">
        <span class="w-16 h-16 rounded-full bg-slate-100 grid place-items-center">
          <NavIcon name="chat" :size="28" />
        </span>
        <p>یک گفتگو را از فهرست انتخاب کنید.</p>
        <button class="office-btn-ghost text-xs" @click="myId && openThread(myId)">
          <NavIcon name="bookmark" :size="14" /> پیام‌های ذخیره‌شده
        </button>
      </div>
    </section>

    <FormModal
      v-if="makingGroup"
      title="گروه جدید"
      :saving="savingGroup"
      :error="groupError"
      save-label="ساختن گروه"
      @close="makingGroup = false"
      @save="createGroup"
    >
      <div class="space-y-4">
        <div>
          <label class="office-label">نام گروه</label>
          <input v-model="groupForm.title" class="office-input" placeholder="مثلاً هماهنگی تولید" />
        </div>
        <div>
          <label class="office-label">اعضا</label>
          <PeoplePicker v-model="groupForm.members" :people="people" />
          <p class="text-[11px] text-slate-400 mt-1.5">شما همیشه عضو گروه می‌مانید.</p>
        </div>
      </div>
    </FormModal>
  </div>
</template>
