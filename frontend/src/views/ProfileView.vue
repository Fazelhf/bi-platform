<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { socialApi, type Note, type TeamMember } from "@/api/social";
import { useAuthStore } from "@/stores/auth";
import UserAvatar from "@/components/UserAvatar.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const member = ref<TeamMember | null>(null);
const notes = ref<Note[]>([]);
const newNote = ref("");
const loading = ref(true);

// If no :id, show my own profile.
const targetId = computed(() =>
  route.params.id ? Number(route.params.id) : null,
);
const isMe = computed(() => !targetId.value || member.value?.username === auth.me?.username);

function lastSeenText(m: TeamMember): string {
  if (m.is_online) return "هم‌اکنون آنلاین";
  if (!m.last_seen) return "آفلاین";
  const mins = Math.round((Date.now() - new Date(m.last_seen).getTime()) / 60000);
  if (mins < 60) return `آخرین بازدید ${mins} دقیقه پیش`;
  const h = Math.round(mins / 60);
  if (h < 24) return `آخرین بازدید ${h} ساعت پیش`;
  return `آخرین بازدید ${Math.round(h / 24)} روز پیش`;
}

async function load() {
  loading.value = true;
  const team = await socialApi.team();
  member.value = targetId.value
    ? team.find((m) => m.id === targetId.value) ?? null
    : team.find((m) => m.username === auth.me?.username) ?? null;
  if (member.value && !isMe.value) {
    notes.value = await socialApi.notes(member.value.id);
  } else {
    notes.value = [];
  }
  loading.value = false;
}

async function addNote() {
  if (!newNote.value.trim() || !member.value) return;
  await socialApi.createNote({ body: newNote.value, subject: member.value.id });
  newNote.value = "";
  notes.value = await socialApi.notes(member.value.id);
}

function openChat() {
  if (member.value) router.push({ name: "chat", query: { with: String(member.value.id) } });
}

onMounted(load);
watch(() => route.params.id, load);
</script>

<template>
  <div v-if="loading" class="text-slate-400">در حال بارگذاری…</div>
  <div v-else-if="member" class="max-w-3xl space-y-4">
    <!-- Header card -->
    <div class="bg-white rounded-card shadow-soft p-6 flex items-center gap-5">
      <UserAvatar :name="member.name" :initials="member.initials" :color="member.avatar_color" :online="member.is_online" :size="80" />
      <div class="flex-1">
        <h1 class="text-xl font-bold text-ink">{{ member.name }}</h1>
        <p class="text-slate-500">{{ member.job_title_fa || member.department_label }}</p>
        <p class="text-sm mt-1" :class="member.is_online ? 'text-accent-600' : 'text-slate-400'">
          ● {{ lastSeenText(member) }}
        </p>
      </div>
      <div v-if="!isMe" class="flex gap-2">
        <button class="px-4 py-2 rounded-xl bg-ink text-white text-sm hover:bg-ink-soft" @click="openChat">💬 گفتگو</button>
        <a
          v-if="member.phone"
          :href="`tel:${member.phone}`"
          class="px-4 py-2 rounded-xl bg-slate-100 text-ink text-sm hover:bg-slate-200"
        >📞 تماس</a>
      </div>
    </div>

    <!-- Details -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-white rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-400 mb-1">نقش</p>
        <p class="font-medium text-ink">{{ member.role }}</p>
      </div>
      <div class="bg-white rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-400 mb-1">بخش</p>
        <p class="font-medium text-ink">{{ member.department_label }}</p>
      </div>
      <div class="bg-white rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-400 mb-1">تلفن</p>
        <p class="font-medium text-ink ltr-nums">{{ member.phone || "—" }}</p>
      </div>
      <div class="bg-white rounded-card shadow-soft p-4">
        <p class="text-xs text-slate-400 mb-1">نام کاربری</p>
        <p class="font-medium text-ink ltr-nums">{{ member.username }}</p>
      </div>
    </div>

    <!-- Notes about this person (only on colleagues) -->
    <div v-if="!isMe" class="bg-ink text-white rounded-card shadow-soft p-5">
      <h2 class="font-bold mb-3">یادداشت‌های من درباره‌ی {{ member.name }}</h2>
      <div class="flex gap-2 mb-3">
        <input
          v-model="newNote"
          placeholder="یادداشت جدید…"
          class="flex-1 bg-white/10 rounded-lg px-3 py-2 text-sm outline-none placeholder-white/40"
          @keyup.enter="addNote"
        />
        <button class="bg-accent-500 hover:bg-accent-600 rounded-lg px-4 text-sm" @click="addNote">افزودن</button>
      </div>
      <p v-if="!notes.length" class="text-white/40 text-sm">یادداشتی ثبت نشده.</p>
      <div v-for="n in notes" :key="n.id" class="bg-white/5 rounded-xl p-3 mb-2 text-sm">
        {{ n.body }}
      </div>
    </div>
  </div>
  <div v-else class="text-slate-400">کاربر یافت نشد.</div>
</template>
