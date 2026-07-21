<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { socialApi, type ChatMessage, type TeamMember } from "@/api/social";
import { useAuthStore } from "@/stores/auth";
import UserAvatar from "@/components/UserAvatar.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const contacts = ref<TeamMember[]>([]);
const unread = ref<Record<string, number>>({});
const activeId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const threadEl = ref<HTMLElement | null>(null);
let timer: number | undefined;

const active = computed(() => contacts.value.find((c) => c.id === activeId.value) || null);
const myId = ref<number | null>(null);

async function loadContacts() {
  const team = await socialApi.team();
  // Everyone except me.
  contacts.value = team.filter((m) => m.username !== auth.me?.username);
  myId.value = team.find((m) => m.username === auth.me?.username)?.id ?? null;
  unread.value = (await socialApi.unreadMessages()).by_sender;
}

async function openThread(id: number) {
  activeId.value = id;
  router.replace({ name: "chat", query: { with: String(id) } });
  messages.value = await socialApi.conversation(id);
  unread.value = { ...unread.value, [id]: 0 };
  await scrollDown();
}

async function send() {
  if (!draft.value.trim() || !activeId.value) return;
  const body = draft.value.trim();
  draft.value = "";
  const msg = await socialApi.sendMessage(activeId.value, body);
  messages.value.push(msg);
  await scrollDown();
}

async function poll() {
  if (activeId.value) {
    messages.value = await socialApi.conversation(activeId.value);
  }
  unread.value = (await socialApi.unreadMessages()).by_sender;
}

async function scrollDown() {
  await nextTick();
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight;
}

function fmt(iso: string) {
  return new Intl.DateTimeFormat("fa-IR", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

onMounted(async () => {
  await loadContacts();
  const withId = Number(route.query.with);
  if (withId) await openThread(withId);
  timer = window.setInterval(poll, 8_000);
});
onBeforeUnmount(() => window.clearInterval(timer));
watch(() => route.query.with, (v) => { if (v) openThread(Number(v)); });
</script>

<template>
  <div class="bg-white rounded-card shadow-soft overflow-hidden flex" style="height: calc(100vh - 8rem)">
    <!-- Contacts -->
    <div class="w-72 border-l border-slate-100 flex flex-col shrink-0">
      <div class="p-4 font-bold text-ink border-b border-slate-100">گفتگوها</div>
      <div class="flex-1 overflow-y-auto">
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
    <div class="flex-1 flex flex-col min-w-0">
      <template v-if="active">
        <div class="flex items-center gap-3 p-4 border-b border-slate-100">
          <UserAvatar :name="active.name" :initials="active.initials" :color="active.avatar_color" :online="active.is_online" :size="40" />
          <div>
            <p class="font-semibold text-ink">{{ active.name }}</p>
            <p class="text-xs" :class="active.is_online ? 'text-accent-600' : 'text-slate-400'">
              {{ active.is_online ? "آنلاین" : "آفلاین" }}
            </p>
          </div>
        </div>

        <div ref="threadEl" class="flex-1 overflow-y-auto p-4 space-y-2 bg-canvas/40">
          <p v-if="!messages.length" class="text-center text-slate-400 text-sm mt-8">
            هنوز پیامی رد و بدل نشده. اولین پیام را بفرستید.
          </p>
          <div
            v-for="m in messages"
            :key="m.id"
            class="flex"
            :class="m.sender === myId ? 'justify-start' : 'justify-end'"
          >
            <div
              class="max-w-[70%] rounded-2xl px-4 py-2 text-sm"
              :class="m.sender === myId ? 'bg-ink text-white rounded-tl-md' : 'bg-white shadow-soft text-ink rounded-tr-md'"
            >
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
  </div>
</template>
