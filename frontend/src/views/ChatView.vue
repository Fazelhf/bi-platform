<script setup lang="ts">
/**
 * گفتگو — direct threads and groups, told apart by a tab.
 *
 * They were stacked in one column under two small headings, which put a
 * fourteen-person group and a colleague on the same visual footing and made
 * the list unreadable once either half grew. Three tabs instead:
 *
 *   همه      — everything with a message in it, newest first
 *   گروه‌ها   — groups only
 *   اعضا     — the directory, for starting a conversation that has none yet
 *
 * «همه» is sorted by last message rather than grouped by kind, because once
 * you are looking for a conversation you remember *when* you last spoke, not
 * whether it was a group.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { socialApi, type ChatMessage, type TeamMember } from "@/api/social";
import { workApi, type ChatGroup, type ChatMessageRow } from "@/api/officeWork";
import { officeApi, type Person } from "@/api/office";
import { useAuthStore } from "@/stores/auth";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import FormModal from "@/components/crm/FormModal.vue";
import UserAvatar from "@/components/UserAvatar.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

type Tab = "all" | "groups" | "people";
const tab = ref<Tab>("all");

const contacts = ref<TeamMember[]>([]);
const groups = ref<ChatGroup[]>([]);
const people = ref<Person[]>([]);
const unread = ref<Record<string, number>>({});
const activeId = ref<number | null>(null);
const activeGroupId = ref<number | null>(null);
const messages = ref<(ChatMessage | ChatMessageRow)[]>([]);
const draft = ref("");

/** What the next message answers, and the files going with it. */
const replyTo = ref<ChatMessageRow | null>(null);
const pending = ref<{ name: string; mime: string; content: string; size: number }[]>([]);
const MAX_BYTES = 5 * 1024 * 1024;
const sendError = ref("");

/** The six that cover almost every reaction anyone actually sends. */
const EMOJI = ["👍", "❤️", "😂", "🙏", "👏", "✅"];
const reactingTo = ref<number | null>(null);

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

async function react(m: ChatMessageRow, emoji: string) {
  reactingTo.value = null;
  const { reactions } = await workApi.react(m.id, emoji);
  // Patch in place so the thread does not jump while you are reading it.
  const row = messages.value.find((x) => x.id === m.id) as ChatMessageRow | undefined;
  if (row) row.reactions = reactions;
}

async function openAttachment(m: ChatMessageRow, attId: number, name: string) {
  const file = activeGroupId.value
    ? await workApi.chatAttachment(m.id, attId)
    : await socialApi.directAttachment(attId);
  const a = document.createElement("a");
  a.href = file.content;
  a.download = name;
  a.click();
}

/** Images are shown, not downloaded — that is the point of sending one. */
const previews = ref<Record<number, string>>({});
async function loadPreview(m: ChatMessageRow, att: { id: number; is_image: boolean }) {
  if (!att.is_image || previews.value[att.id]) return;
  const file = activeGroupId.value
    ? await workApi.chatAttachment(m.id, att.id)
    : await socialApi.directAttachment(att.id);
  previews.value[att.id] = file.content;
}
const threadEl = ref<HTMLElement | null>(null);
let timer: number | undefined;

const active = computed(() => contacts.value.find((c) => c.id === activeId.value) || null);
const activeGroup = computed(
  () => groups.value.find((g) => g.id === activeGroupId.value) || null,
);
const isSavedOpen = computed(() => !!myId.value && activeId.value === myId.value);
/**
 * Whether a conversation is open at all.
 *
 * `active` is looked up in `contacts`, which deliberately excludes you — so
 * the saved-messages thread has no contact row and has to be counted
 * separately, or opening it leaves the pane on the empty placeholder while
 * the URL says a thread is open.
 */
const hasThread = computed(
  () => !!active.value || !!activeGroup.value || isSavedOpen.value,
);
const myId = ref<number | null>(null);

/** A group message carries its sender; a direct one is «me or them». */
function senderOf(m: ChatMessage | ChatMessageRow): number {
  return (m as ChatMessageRow).sender ?? (m as ChatMessage).sender;
}
function senderName(m: ChatMessage | ChatMessageRow): string {
  return (m as ChatMessageRow).sender_detail?.name ?? "";
}

/** Last-activity time for a direct thread, from the overview payload. */
const directMeta = ref<Record<number, { last_at: string; last_message: string }>>({});

/**
 * «همه» — one list ordered by when you last spoke, groups and people mixed.
 * Anything never spoken to belongs in «اعضا», not here.
 */
/**
 * «پیام‌های ذخیره‌شده» — the thread with yourself.
 *
 * Where a link, a phone number or a half-formed thought goes when it is not
 * for anybody else. It needs no new model: a message whose sender and
 * recipient are the same person already describes one. Pinned to the top of
 * every tab, because it is the one conversation you always want reachable
 * and it must never sink under a busy day.
 */
async function openSaved() {
  if (!myId.value) return;
  await openThread(myId.value);
}

const allThreads = computed(() => {
  const rows: {
    key: string; id: number; kind: "group" | "direct";
    title: string; sub: string; at: string; unread: number; person?: TeamMember;
  }[] = [];

  for (const g of groups.value) {
    rows.push({
      key: `g${g.id}`, id: g.id, kind: "group", title: g.title,
      sub: g.last_message || `${g.member_count} عضو`,
      at: g.last_at ?? "", unread: g.unread,
    });
  }
  for (const c of contacts.value) {
    const meta = directMeta.value[c.id];
    // Saved messages has its own permanent row above the list.
    if (!meta || c.id === myId.value) continue;
    rows.push({
      key: `d${c.id}`, id: c.id, kind: "direct", title: c.name,
      sub: meta.last_message, at: meta.last_at,
      unread: unread.value[c.id] ?? 0, person: c,
    });
  }
  return rows.sort((a, b) => (b.at || "").localeCompare(a.at || ""));
});

async function loadContacts() {
  const team = await socialApi.team();
  contacts.value = team.filter((m) => m.username !== auth.me?.username);
  // From the account itself, not by matching a username against the sales
  // roster: someone who is not on it used to get `null` here, which put
  // every bubble in their thread on the wrong side and made the saved-
  // messages row do nothing at all.
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

async function openThread(id: number) {
  activeGroupId.value = null;
  activeId.value = id;
  router.replace({ name: "chat", query: { with: String(id) } });
  messages.value = await socialApi.conversation(id);
  unread.value = { ...unread.value, [id]: 0 };
  await scrollDown();
}

async function openGroup(id: number) {
  activeId.value = null;
  activeGroupId.value = id;
  router.replace({ name: "chat", query: { group: String(id) } });
  const data = await workApi.group(id);
  messages.value = data.messages;
  // Opening clears the badge; the server moved the read marker on GET.
  const row = groups.value.find((g) => g.id === id);
  if (row) row.unread = 0;
  await scrollDown();
}

async function send() {
  const body = draft.value.trim();
  // A file with no words is a normal message, not an empty one.
  if (!body && !pending.value.length) return;
  const files = pending.value.map(({ name, mime, content }) => ({ name, mime, content }));
  const parent = replyTo.value?.id ?? null;

  draft.value = "";
  pending.value = [];
  replyTo.value = null;
  sendError.value = "";

  try {
    if (activeGroupId.value) {
      messages.value.push(
        await workApi.postToGroup(activeGroupId.value, body, {
          reply_to: parent, attachments: files,
        }),
      );
    } else if (activeId.value) {
      messages.value.push(
        await socialApi.sendMessage(activeId.value, body, {
          reply_to: parent, attachments: files,
        }),
      );
    }
  } catch {
    sendError.value = "ارسال نشد. دوباره تلاش کنید.";
  }
  await scrollDown();
}

async function poll() {
  if (activeGroupId.value) {
    messages.value = (await workApi.group(activeGroupId.value)).messages;
  } else if (activeId.value) {
    messages.value = await socialApi.conversation(activeId.value);
  }
  unread.value = (await socialApi.unreadMessages()).by_sender;
  await loadGroups();
}

async function scrollDown() {
  await nextTick();
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight;
}

function fmt(iso: string) {
  return new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

// -- new group ---------------------------------------------------------
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
  } catch {
    groupError.value = "ساخت گروه انجام نشد.";
  } finally {
    savingGroup.value = false;
  }
}

onMounted(async () => {
  officeApi.people().then((d) => (people.value = d.people)).catch(() => {});
  await Promise.all([loadContacts(), loadGroups()]);
  const withId = Number(route.query.with);
  const groupId = Number(route.query.group);
  if (groupId) await openGroup(groupId);
  else if (withId) await openThread(withId);
  timer = window.setInterval(poll, 8_000);
});
onBeforeUnmount(() => window.clearInterval(timer));
watch(() => route.query.with, (v) => { if (v) openThread(Number(v)); });
watch(() => route.query.group, (v) => { if (v) openGroup(Number(v)); });
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft overflow-hidden flex" style="height: calc(100vh - 8rem)">
    <!-- List — full width on mobile; hidden there once a thread is open -->
    <div
      class="w-full md:w-72 border-l border-slate-100 flex-col shrink-0"
      :class="!hasThread ? 'flex' : 'hidden md:flex'"
    >
      <div class="px-3 pt-3 pb-2 border-b border-slate-100">
        <div class="flex items-center justify-between mb-2">
          <span class="font-bold text-ink text-sm">گفتگو</span>
          <button
            class="text-xs text-slate-500 hover:text-ink"
            @click="makingGroup = true"
          >+ گروه</button>
        </div>
        <div class="flex bg-slate-100 rounded-xl p-0.5 text-xs">
          <button
            v-for="t in ([
              { key: 'all', label: 'همه' },
              { key: 'groups', label: 'گروه‌ها' },
              { key: 'people', label: 'اعضا' },
            ] as const)"
            :key="t.key"
            class="flex-1 py-1.5 rounded-lg transition-colors"
            :class="tab === t.key ? 'bg-surface text-ink shadow-soft font-medium' : 'text-slate-500'"
            @click="tab = t.key"
          >{{ t.label }}</button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto">
        <!-- Always first, in every tab. -->
        <button
          class="w-full flex items-center gap-3 px-4 py-3 border-b border-slate-100
                 hover:bg-slate-50 transition text-right"
          :class="isSavedOpen ? 'bg-slate-100' : ''"
          @click="openSaved"
        >
          <span class="w-[42px] h-[42px] rounded-full bg-panel text-white grid place-items-center shrink-0">
            🔖
          </span>
          <span class="flex-1 min-w-0">
            <span class="block text-sm font-medium text-ink truncate">پیام‌های ذخیره‌شده</span>
            <span class="block text-xs text-slate-400 truncate">یادداشت‌ها و لینک‌های خودتان</span>
          </span>
        </button>

        <!-- همه: whatever has been spoken in, newest first -->
        <template v-if="tab === 'all'">
          <p v-if="!allThreads.length" class="text-center text-slate-400 text-xs py-8">
            هنوز گفتگویی شروع نشده. از «اعضا» یک نفر را انتخاب کنید.
          </p>
          <button
            v-for="row in allThreads" :key="row.key"
            class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition text-right"
            :class="(row.kind === 'group' ? activeGroupId : activeId) === row.id ? 'bg-slate-100' : ''"
            @click="row.kind === 'group' ? openGroup(row.id) : openThread(row.id)"
          >
            <span
              v-if="row.kind === 'group'"
              class="w-[42px] h-[42px] rounded-full bg-panel text-white grid place-items-center text-[10px] shrink-0"
            >گروه</span>
            <UserAvatar
              v-else-if="row.person"
              :name="row.person.name" :initials="row.person.initials"
              :color="row.person.avatar_color" :online="row.person.is_online" :size="42"
            />
            <span class="flex-1 min-w-0">
              <span class="block text-sm font-medium text-ink truncate">{{ row.title }}</span>
              <span class="block text-xs text-slate-400 truncate">{{ row.sub }}</span>
            </span>
            <span
              v-if="row.unread"
              class="bg-accent-500 text-white text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center ltr-nums shrink-0"
            >{{ row.unread }}</span>
          </button>
        </template>

        <!-- گروه‌ها -->
        <template v-else-if="tab === 'groups'">
          <p v-if="!groups.length" class="text-center text-slate-400 text-xs py-8">
            گروهی نساخته‌اید.
          </p>
          <button
            v-for="g in groups" :key="`g${g.id}`"
            class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition text-right"
            :class="activeGroupId === g.id ? 'bg-slate-100' : ''"
            @click="openGroup(g.id)"
          >
            <span class="w-[42px] h-[42px] rounded-full bg-panel text-white grid place-items-center text-[10px] shrink-0">
              گروه
            </span>
            <span class="flex-1 min-w-0">
              <span class="block text-sm font-medium text-ink truncate">{{ g.title }}</span>
              <span class="block text-xs text-slate-400 truncate">
                {{ g.last_message || `${g.member_count} عضو` }}
              </span>
            </span>
            <span
              v-if="g.unread"
              class="bg-accent-500 text-white text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center ltr-nums shrink-0"
            >{{ g.unread }}</span>
          </button>
        </template>

        <!-- اعضا: the directory, including people never spoken to -->
        <template v-else>
          <button
            v-for="c in contacts" :key="c.id"
            class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition text-right"
            :class="activeId === c.id ? 'bg-slate-100' : ''"
            @click="openThread(c.id)"
          >
            <UserAvatar :name="c.name" :initials="c.initials" :color="c.avatar_color" :online="c.is_online" :size="42" />
            <span class="flex-1 min-w-0">
              <span class="block text-sm font-medium text-ink truncate">{{ c.name }}</span>
              <span class="block text-xs text-slate-400 truncate">{{ c.job_title_fa }}</span>
            </span>
            <span
              v-if="unread[c.id]"
              class="bg-accent-500 text-white text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center shrink-0"
            >{{ unread[c.id] }}</span>
          </button>
        </template>
      </div>
    </div>

    <!-- Thread -->
    <div
      class="flex-1 flex-col min-w-0"
      :class="!hasThread ? 'hidden md:flex' : 'flex'"
    >
      <template v-if="hasThread">
        <div class="flex items-center gap-3 p-4 border-b border-slate-100">
          <button
            class="md:hidden -mr-1 p-1 text-slate-500 hover:text-ink text-xl leading-none shrink-0"
            title="بازگشت به فهرست"
            @click="activeId = null; activeGroupId = null"
          >→</button>

          <template v-if="isSavedOpen">
            <span class="w-10 h-10 rounded-full bg-panel text-white grid place-items-center shrink-0">
              🔖
            </span>
            <div>
              <p class="font-semibold text-ink">پیام‌های ذخیره‌شده</p>
              <p class="text-xs text-slate-400">فقط خودتان می‌بینید</p>
            </div>
          </template>
          <template v-else-if="activeGroup">
            <span class="w-10 h-10 rounded-full bg-panel text-white grid place-items-center text-xs shrink-0">
              گروه
            </span>
            <div>
              <p class="font-semibold text-ink">{{ activeGroup.title }}</p>
              <p class="text-xs text-slate-400 ltr-nums">{{ activeGroup.member_count }} عضو</p>
            </div>
          </template>
          <template v-else-if="active">
            <UserAvatar :name="active.name" :initials="active.initials" :color="active.avatar_color" :online="active.is_online" :size="40" />
            <div>
              <p class="font-semibold text-ink">{{ active.name }}</p>
              <p class="text-xs" :class="active.is_online ? 'text-accent-600' : 'text-slate-400'">
                {{ active.is_online ? "آنلاین" : "آفلاین" }}
              </p>
            </div>
          </template>
        </div>

        <div ref="threadEl" class="flex-1 overflow-y-auto p-4 space-y-2 bg-canvas/40">
          <p v-if="!messages.length" class="text-center text-slate-400 text-sm mt-8">
            هنوز پیامی رد و بدل نشده. اولین پیام را بفرستید.
          </p>
          <div
            v-for="m in messages"
            :key="m.id"
            class="flex"
            :class="senderOf(m) === myId ? 'justify-start' : 'justify-end'"
          >
            <div
              class="max-w-[70%] rounded-2xl px-4 py-2 text-sm"
              :class="senderOf(m) === myId ? 'bg-panel text-white rounded-tl-md' : 'bg-surface shadow-soft text-ink rounded-tr-md'"
            >
              <!-- In a group, who spoke is not obvious from the side alone. -->
              <p
                v-if="activeGroup && senderOf(m) !== myId && senderName(m)"
                class="text-[11px] font-medium opacity-70 mb-0.5"
              >{{ senderName(m) }}</p>

              <!-- What this answers. Truncated on purpose: quoting the whole
                   parent nests without end in a long back-and-forth. -->
              <div
                v-if="(m as any).reply_to"
                class="border-r-2 border-current/40 pr-2 mb-1.5 opacity-70 text-[11px]"
              >
                <span class="font-medium">{{ (m as any).reply_to.sender_name }}</span>
                <span class="block truncate">{{ (m as any).reply_to.body }}</span>
              </div>

              <p v-if="m.body" class="leading-6 whitespace-pre-wrap">{{ m.body }}</p>

              <div v-if="(m as any).attachments?.length" class="space-y-1.5 mt-1">
                <template v-for="a in (m as any).attachments" :key="a.id">
                  <img
                    v-if="a.is_image"
                    :src="previews[a.id]"
                    class="rounded-xl max-h-56 cursor-pointer"
                    :alt="a.name"
                    @vue:mounted="loadPreview(m as any, a)"
                    @click="openAttachment(m as any, a.id, a.name)"
                  />
                  <button
                    v-else
                    class="flex items-center gap-2 bg-black/10 rounded-lg px-2 py-1.5 text-[11px] w-full"
                    @click="openAttachment(m as any, a.id, a.name)"
                  >
                    📎 <span class="truncate flex-1 text-right">{{ a.name }}</span>
                    <span class="opacity-60 ltr-nums">
                      {{ Math.max(1, Math.round(a.size_bytes / 1024)) }}KB
                    </span>
                  </button>
                </template>
              </div>

              <div class="flex items-center gap-1.5 mt-1">
                <p class="text-[10px] opacity-60 ltr-nums">{{ fmt(m.created_at) }}</p>
                <button
                  class="text-[10px] opacity-50 hover:opacity-100"
                  title="پاسخ"
                  @click="replyTo = (m as any)"
                >پاسخ</button>
                <button
                  class="text-[10px] opacity-50 hover:opacity-100"
                  title="واکنش"
                  @click="reactingTo = reactingTo === m.id ? null : m.id"
                >واکنش</button>
              </div>

              <!-- Given reactions, grouped. Yours is outlined, so the same
                   tap that gave it takes it back. -->
              <div v-if="(m as any).reactions?.length" class="flex flex-wrap gap-1 mt-1">
                <button
                  v-for="r in (m as any).reactions" :key="r.emoji"
                  class="text-[11px] rounded-full px-1.5 py-0.5 bg-black/10 ltr-nums"
                  :class="r.mine ? 'ring-1 ring-current' : ''"
                  @click="react(m as any, r.emoji)"
                >{{ r.emoji }} {{ r.count }}</button>
              </div>

              <div
                v-if="reactingTo === m.id"
                class="flex gap-1 mt-1 bg-surface rounded-xl p-1 shadow-pop"
              >
                <button
                  v-for="e in EMOJI" :key="e"
                  class="text-base leading-none px-1 hover:scale-125 transition-transform"
                  @click="react(m as any, e)"
                >{{ e }}</button>
              </div>
            </div>
          </div>
        </div>

        <div class="border-t border-slate-100">
          <!-- What you are answering, with a way out of it. -->
          <div
            v-if="replyTo"
            class="px-3 pt-2 flex items-start gap-2 text-xs text-slate-500"
          >
            <span class="border-r-2 border-slate-300 pr-2 flex-1 min-w-0">
              <span class="font-medium">پاسخ به {{ replyTo.sender_detail?.name }}</span>
              <span class="block truncate">{{ replyTo.body || "پیوست" }}</span>
            </span>
            <button class="text-slate-400 hover:text-red-500" @click="replyTo = null">×</button>
          </div>

          <div v-if="pending.length" class="px-3 pt-2 flex flex-wrap gap-1.5">
            <span
              v-for="(f, i) in pending" :key="i"
              class="flex items-center gap-1.5 bg-slate-100 rounded-lg px-2 py-1 text-[11px]"
            >
              <span class="truncate max-w-[9rem]">{{ f.name }}</span>
              <button class="text-slate-400 hover:text-red-500" @click="pending.splice(i, 1)">×</button>
            </span>
          </div>

          <p v-if="sendError" class="px-3 pt-2 text-[11px] text-red-600">{{ sendError }}</p>

          <form class="p-3 flex items-center gap-2" @submit.prevent="send">
            <label
              class="w-10 h-10 rounded-full bg-slate-100 hover:bg-slate-200 grid place-items-center
                     shrink-0 cursor-pointer text-slate-500"
              title="پیوست فایل"
            >
              📎
              <input type="file" multiple class="hidden" @change="pickFiles" />
            </label>
            <input
              v-model="draft"
              placeholder="پیام خود را بنویسید…"
              class="flex-1 bg-slate-100 rounded-full px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-accent-500"
            />
            <button
              type="submit"
              class="w-11 h-11 rounded-full bg-accent-500 hover:bg-accent-600 text-white flex items-center justify-center shrink-0"
            >➤</button>
          </form>
        </div>
      </template>

      <div v-else class="flex-1 flex flex-col items-center justify-center gap-2 text-slate-400 text-sm">
        <p>یک گفتگو را از فهرست انتخاب کنید.</p>
        <button class="text-xs underline hover:text-ink" @click="openSaved">
          یا در پیام‌های ذخیره‌شده چیزی برای خودتان بنویسید
        </button>
      </div>
    </div>

    <FormModal
      v-if="makingGroup"
      title="گروه جدید"
      :saving="savingGroup"
      :error="groupError"
      save-label="ساختن گروه"
      @close="makingGroup = false"
      @save="createGroup"
    >
      <div class="space-y-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">نام گروه</label>
          <input
            v-model="groupForm.title"
            class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300"
            placeholder="مثلاً هماهنگی تولید"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">اعضا</label>
          <PeoplePicker v-model="groupForm.members" :people="people" />
          <p class="text-[11px] text-slate-400 mt-1">شما همیشه عضو گروه می‌مانید.</p>
        </div>
      </div>
    </FormModal>
  </div>
</template>
