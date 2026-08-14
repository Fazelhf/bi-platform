<script setup lang="ts">
/**
 * گفتگو — direct threads and groups in one list.
 *
 * Groups were added beside the 1:1 chat rather than as a second page: they
 * are the same activity, and two pages would mean checking two places for
 * «آیا کسی پیام داده». The list is one column with a heading in the middle;
 * the thread pane is shared, because a group thread and a direct thread
 * differ only in whose name sits above each bubble.
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

const contacts = ref<TeamMember[]>([]);
const groups = ref<ChatGroup[]>([]);
const people = ref<Person[]>([]);
const unread = ref<Record<string, number>>({});
const activeId = ref<number | null>(null);
const activeGroupId = ref<number | null>(null);
const messages = ref<(ChatMessage | ChatMessageRow)[]>([]);
const draft = ref("");
const threadEl = ref<HTMLElement | null>(null);
let timer: number | undefined;

const active = computed(() => contacts.value.find((c) => c.id === activeId.value) || null);
const activeGroup = computed(
  () => groups.value.find((g) => g.id === activeGroupId.value) || null,
);
const hasThread = computed(() => !!active.value || !!activeGroup.value);
const myId = ref<number | null>(null);

/** A group message carries its sender; a direct one is «me or them». */
function senderOf(m: ChatMessage | ChatMessageRow): number {
  return (m as ChatMessageRow).sender ?? (m as ChatMessage).sender;
}
function senderName(m: ChatMessage | ChatMessageRow): string {
  return (m as ChatMessageRow).sender_detail?.name ?? "";
}

async function loadContacts() {
  const team = await socialApi.team();
  contacts.value = team.filter((m) => m.username !== auth.me?.username);
  myId.value = team.find((m) => m.username === auth.me?.username)?.id ?? null;
  unread.value = (await socialApi.unreadMessages()).by_sender;
}

async function loadGroups() {
  try {
    groups.value = (await workApi.chatOverview()).groups;
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
  if (!body) return;
  draft.value = "";
  if (activeGroupId.value) {
    messages.value.push(await workApi.postToGroup(activeGroupId.value, body));
  } else if (activeId.value) {
    messages.value.push(await socialApi.sendMessage(activeId.value, body));
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
      <div class="p-4 flex items-center justify-between border-b border-slate-100">
        <span class="font-bold text-ink">گفتگوها</span>
        <button
          class="text-xs text-slate-500 hover:text-ink"
          @click="makingGroup = true"
        >+ گروه</button>
      </div>

      <div class="flex-1 overflow-y-auto">
        <template v-if="groups.length">
          <p class="px-4 pt-3 pb-1 text-[11px] text-slate-400">گروه‌ها</p>
          <button
            v-for="g in groups" :key="`g${g.id}`"
            class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition text-right"
            :class="activeGroupId === g.id ? 'bg-slate-100' : ''"
            @click="openGroup(g.id)"
          >
            <span class="w-[42px] h-[42px] rounded-full bg-panel text-white grid place-items-center text-xs shrink-0">
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
              class="bg-accent-500 text-white text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center ltr-nums"
            >{{ g.unread }}</span>
          </button>
          <p class="px-4 pt-3 pb-1 text-[11px] text-slate-400">افراد</p>
        </template>

        <button
          v-for="c in contacts"
          :key="c.id"
          class="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 transition text-right"
          :class="activeId === c.id ? 'bg-slate-100' : ''"
          @click="openThread(c.id)"
        >
          <UserAvatar :name="c.name" :initials="c.initials" :color="c.avatar_color" :online="c.is_online" :size="42" />
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-ink truncate">{{ c.name }}</p>
            <p class="text-xs text-slate-400 truncate">{{ c.job_title_fa }}</p>
          </div>
          <span
            v-if="unread[c.id]"
            class="bg-accent-500 text-white text-[11px] font-bold rounded-full min-w-[20px] h-5 px-1.5 leading-5 text-center"
          >{{ unread[c.id] }}</span>
        </button>
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

          <template v-if="activeGroup">
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
              <p class="leading-6 whitespace-pre-wrap">{{ m.body }}</p>
              <p class="text-[10px] mt-1 opacity-60 ltr-nums">{{ fmt(m.created_at) }}</p>
            </div>
          </div>
        </div>

        <form class="p-3 border-t border-slate-100 flex items-center gap-2" @submit.prevent="send">
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
      </template>

      <div v-else class="flex-1 flex items-center justify-center text-slate-400 text-sm">
        یک گفتگو را از فهرست انتخاب کنید.
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
