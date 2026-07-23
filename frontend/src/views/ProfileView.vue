<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { socialApi, type Note, type TeamMember } from "@/api/social";
import { useAuthStore } from "@/stores/auth";
import { toast, confirm } from "@/composables/useUi";
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

// --- Edit own profile ---
const editing = ref(false);
const form = ref({ display_name_fa: "", job_title_fa: "", phone: "", avatar_color: "", avatar_image: "" });
const AVATAR_COLORS = ["#10b981", "#3b6fed", "#f59e0b", "#ec4899", "#8b5cf6", "#1c1c1e", "#ef4444", "#0ea5e9"];

function openEdit() {
  if (!member.value) return;
  form.value = {
    display_name_fa: member.value.name,
    job_title_fa: member.value.job_title_fa,
    phone: member.value.phone,
    avatar_color: member.value.avatar_color || "#3b6fed",
    avatar_image: member.value.avatar_image || "",
  };
  editing.value = true;
}

// Resize the chosen photo to a 160px square data-URL — no server files needed.
function onPhoto(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (!file.type.startsWith("image/")) { toast.error("فقط فایل تصویری مجاز است."); return; }
  const img = new Image();
  const reader = new FileReader();
  reader.onload = () => { img.src = reader.result as string; };
  img.onload = () => {
    const S = 160;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = S;
    const ctx = canvas.getContext("2d")!;
    const side = Math.min(img.width, img.height);
    ctx.drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, S, S);
    form.value.avatar_image = canvas.toDataURL("image/jpeg", 0.82);
  };
  reader.readAsDataURL(file);
}
async function saveProfile() {
  try {
    await socialApi.updateMe(form.value);
    toast.success("پروفایل به‌روزرسانی شد.");
  } catch {
    toast.error("ذخیره نشد — شاید عکس بزرگ است.");
    return;
  }
  editing.value = false;
  await auth.fetchMe();
  await load();
}

// --- Delete account (admin/CEO on a colleague) ---
const canDelete = computed(
  () => !isMe.value && (auth.isExecutive || auth.me?.is_superuser) && member.value?.username !== "admin",
);
async function deleteAccount() {
  if (!member.value) return;
  const ok = await confirm({
    title: "حذف اکانت",
    message: `اکانت «${member.value.name}» برای همیشه حذف شود؟ این عمل قابل بازگشت نیست.`,
    danger: true,
  });
  if (!ok) return;
  try {
    await socialApi.deleteUser(member.value.id);
    toast.success("اکانت حذف شد.");
    router.push({ name: "team" });
  } catch {
    toast.error("حذف انجام نشد (ممکن است دسترسی نداشته باشید).");
  }
}

onMounted(load);
watch(() => route.params.id, load);
</script>

<template>
  <div v-if="loading" class="text-slate-400">در حال بارگذاری…</div>
  <div v-else-if="member" class="max-w-3xl space-y-4">
    <!-- Header card -->
    <div class="bg-white rounded-card shadow-soft p-6 flex items-center gap-5">
      <UserAvatar :name="member.name" :initials="member.initials" :color="member.avatar_color" :image="member.avatar_image" :online="member.is_online" :size="80" />
      <div class="flex-1">
        <h1 class="text-xl font-bold text-ink">{{ member.name }}</h1>
        <p class="text-slate-500">{{ member.job_title_fa || member.department_label }}</p>
        <p class="text-sm mt-1" :class="member.is_online ? 'text-accent-600' : 'text-slate-400'">
          ● {{ lastSeenText(member) }}
        </p>
      </div>
      <div class="flex gap-2">
        <template v-if="!isMe">
          <button class="px-4 py-2 rounded-xl bg-ink text-white text-sm hover:bg-ink-soft" @click="openChat">💬 گفتگو</button>
          <a
            v-if="member.phone"
            :href="`tel:${member.phone}`"
            class="px-4 py-2 rounded-xl bg-slate-100 text-ink text-sm hover:bg-slate-200"
          >📞 تماس</a>
          <button
            v-if="canDelete"
            class="px-4 py-2 rounded-xl bg-red-50 text-red-600 text-sm hover:bg-red-100"
            @click="deleteAccount"
          >🗑 حذف اکانت</button>
        </template>
        <button
          v-else
          class="px-4 py-2 rounded-xl bg-slate-100 text-ink text-sm hover:bg-slate-200"
          @click="openEdit"
        >✎ ویرایش پروفایل</button>
      </div>
    </div>

    <!-- Edit-profile modal -->
    <div v-if="editing" class="fixed inset-0 bg-black/30 flex items-center justify-center z-50" @click.self="editing = false">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-3">
        <h3 class="font-bold text-ink mb-1">ویرایش پروفایل</h3>

        <!-- Photo -->
        <div class="flex items-center gap-4">
          <UserAvatar :name="form.display_name_fa" :color="form.avatar_color" :image="form.avatar_image" :show-dot="false" :size="64" />
          <div class="flex gap-2">
            <label class="px-3 py-1.5 text-sm rounded-lg border border-slate-300 hover:bg-slate-50 cursor-pointer">
              انتخاب عکس
              <input type="file" accept="image/*" class="hidden" @change="onPhoto" />
            </label>
            <button v-if="form.avatar_image" class="px-3 py-1.5 text-sm rounded-lg text-rose-500 hover:bg-rose-50" @click="form.avatar_image = ''">حذف عکس</button>
          </div>
        </div>

        <div>
          <label class="block text-xs text-slate-500 mb-1">نام نمایشی</label>
          <input v-model="form.display_name_fa" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">عنوان شغلی</label>
          <input v-model="form.job_title_fa" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">تلفن</label>
          <input v-model="form.phone" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm ltr-nums" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-2">رنگ آواتار</label>
          <div class="flex gap-2">
            <button
              v-for="c in AVATAR_COLORS" :key="c"
              class="w-8 h-8 rounded-full transition"
              :style="{ backgroundColor: c }"
              :class="form.avatar_color === c ? 'ring-2 ring-offset-2 ring-ink' : ''"
              @click="form.avatar_color = c"
            ></button>
          </div>
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <button class="px-4 py-2 text-sm rounded-lg hover:bg-slate-100" @click="editing = false">انصراف</button>
          <button class="px-4 py-2 text-sm rounded-lg bg-accent-500 text-white hover:bg-accent-600" @click="saveProfile">ذخیره</button>
        </div>
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
