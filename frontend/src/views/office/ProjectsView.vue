<script setup lang="ts">
/**
 * پروژه‌ها — the cards, and what each one is really asking.
 *
 * A card answers three questions in this order: how far along is it, how much
 * of that is mine, and is anything late. Progress alone is the number people
 * quote and the least actionable of the three.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { officeApi, type Person } from "@/api/office";
import { workApi, type Project } from "@/api/officeWork";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate, timeAgo } from "@/utils/adminFormat";
import FormModal from "@/components/crm/FormModal.vue";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import NavIcon from "@/components/NavIcon.vue";

const router = useRouter();

const projects = ref<Project[]>([]);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const editing = ref<Project | null>(null);
const creating = ref(false);
const saving = ref(false);
const search = ref("");

/**
 * The eight a project may wear. Enough to tell a board apart at a glance,
 * few enough that two projects rarely collide — a free colour picker gives
 * you fourteen shades of blue and no way to tell them apart.
 */
const COLORS = [
  "#8b5cf6", "#ef4444", "#f97316", "#f59e0b",
  "#10b981", "#0ea5e9", "#3b6fed", "#64748b",
];

const form = ref({
  name: "", description: "", owner: null as number | null,
  due_on: "", color: COLORS[0], member_ids: [] as number[],
});

const shown = computed(() => {
  const q = search.value.trim();
  return q ? projects.value.filter((p) => p.name.includes(q)) : projects.value;
});

async function load() {
  loading.value = true;
  try {
    projects.value = await workApi.projects();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  officeApi.people().then((d) => (people.value = d.people)).catch(() => {});
  await load();
});

function startNew() {
  form.value = {
    name: "", description: "", owner: null, due_on: "",
    color: COLORS[projects.value.length % COLORS.length], member_ids: [],
  };
  creating.value = true;
}

function startEdit(p: Project) {
  form.value = {
    name: p.name, description: p.description, owner: p.owner,
    due_on: p.due_on ?? "", color: p.color || COLORS[0],
    member_ids: p.memberships.map((m) => m.user),
  };
  editing.value = p;
}

async function save() {
  if (!form.value.name.trim()) {
    error.value = "نام پروژه را بنویسید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await workApi.saveProject(
      { ...form.value, due_on: form.value.due_on || null } as never,
      editing.value?.id,
    );
    creating.value = false;
    editing.value = null;
    await load();
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

/**
 * Finished is green and late is amber regardless of the project's colour —
 * state outranks identity, or a red project would look permanently on fire.
 */
function barStyle(p: Project): Record<string, string> {
  if (p.progress_pct >= 100) return { background: "#10b981" };
  if (p.overdue_count) return { background: "#f59e0b" };
  return { background: p.color || "rgb(var(--sec))" };
}

</script>

<template>
  <div class="space-y-4">
    <div class="office-card p-2.5 flex flex-wrap items-center gap-2">
      <label class="office-search flex-1 min-w-[12rem]">
        <NavIcon name="search" :size="16" />
        <input v-model="search" class="office-input" placeholder="جستجوی نام پروژه…" />
      </label>
      <span class="text-xs text-slate-400 ltr-nums px-1">{{ num(shown.length) }} پروژه</span>
      <button class="office-btn" @click="startNew">
        <NavIcon name="plus" :size="16" /> پروژه جدید
      </button>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-4 py-3">
      {{ error }}
    </p>

    <div v-if="loading" class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      <Skeleton v-for="i in 6" :key="i" class="h-44 rounded-card" />
    </div>

    <EmptyState
      v-else-if="!shown.length"
      title="پروژه‌ای نیست"
      hint="با «پروژه جدید» اولین پروژه را بسازید."
    />

    <!--
      The whole card opens the project; ویرایش sits above it and stops the
      click. Each card leads with the project's own colour and initials, the
      way people recognise a project before they read its name.
    -->
    <div v-else class="grid sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
      <div
        v-for="p in shown" :key="p.id"
        class="group relative office-card hover:shadow-pop hover:-translate-y-0.5 transition-all overflow-hidden"
      >
        <span
          class="absolute inset-x-0 top-0 h-1"
          :style="{ background: p.color || 'rgb(var(--sec))' }"
        ></span>
        <button
          class="w-full text-right p-5 flex flex-col items-center gap-3"
          @click="router.push({ name: 'office-project', params: { id: p.id } })"
        >
          <span
            class="w-16 h-16 rounded-full grid place-items-center text-white text-xl font-bold shadow-soft
                   transition-transform group-hover:scale-105"
            :style="{ background: p.color || 'rgb(var(--sec))' }"
          >{{ p.name.trim().slice(0, 2) }}</span>
          <span class="flex items-center gap-1.5 max-w-full">
            <NavIcon
              v-if="p.progress_pct >= 100"
              name="check" :size="15"
              class="text-white bg-emerald-500 rounded-full p-0.5 shrink-0"
            />
            <span class="font-bold text-ink truncate">{{ p.name }}</span>
          </span>
          <span v-if="p.due_on" class="text-[11px] text-slate-400 ltr-nums -mt-2 flex items-center gap-1">
            <NavIcon name="calendar" :size="11" /> مهلت {{ faDate(p.due_on) }}
          </span>

          <span class="block w-full mt-1">
            <span class="flex items-baseline justify-between text-[11px] mb-1">
              <span class="text-slate-500">وضعیت کل پروژه</span>
              <span class="text-ink font-semibold ltr-nums">{{ num(Math.round(p.progress_pct)) }}٪</span>
            </span>
            <span class="block h-2 bg-slate-100 rounded-full overflow-hidden">
              <span
                class="block h-full rounded-full transition-all duration-500"
                :style="{ width: `${Math.max(p.progress_pct, 1)}%`, ...barStyle(p) }"
              ></span>
            </span>
          </span>

          <span class="flex items-center justify-between w-full text-[11px]">
            <span class="text-slate-400 ltr-nums">
              {{ num(p.done_count) }} از {{ num(p.task_count) }} وظیفه
            </span>
            <span v-if="p.overdue_count" class="text-amber-600 ltr-nums flex items-center gap-0.5">
              <NavIcon name="clock" :size="11" /> {{ num(p.overdue_count) }} عقب‌افتاده
            </span>
          </span>

          <span class="flex items-center justify-between gap-2 w-full pt-3 border-t border-slate-100">
            <span class="flex -space-x-2 space-x-reverse">
              <UserAvatar
                v-for="m in p.memberships.slice(0, 5)" :key="m.id"
                :user="m.user_detail" :size="26"
                class="ring-2 ring-surface rounded-full"
              />
              <span
                v-if="p.memberships.length > 5"
                class="w-[26px] h-[26px] rounded-full bg-slate-100 text-[10px] text-slate-500
                       grid place-items-center ring-2 ring-surface ltr-nums"
              >+{{ num(p.memberships.length - 5) }}</span>
            </span>
            <span
              class="text-[11px] rounded-full px-2 py-0.5 ltr-nums"
              :class="p.my_open_count ? 'office-chip font-medium' : 'text-slate-300'"
            >{{ num(p.my_open_count) }} کار من</span>
          </span>
          <span v-if="p.last_done_at" class="text-[10px] text-slate-400 w-full -mt-1">
            آخرین کار انجام‌شده: {{ timeAgo(p.last_done_at) }}
          </span>
        </button>

        <!-- Layered over the card, so it does not open the project too. -->
        <button
          class="office-icon-btn absolute top-3 left-3 opacity-0 group-hover:opacity-100 focus:opacity-100 [@media(hover:none)]:opacity-100"
          :aria-label="`ویرایش ${p.name}`"
          title="ویرایش پروژه"
          @click.stop="startEdit(p)"
        ><NavIcon name="pencil" :size="15" /></button>
      </div>
    </div>

    <FormModal
      v-if="creating || editing"
      :title="editing ? 'ویرایش پروژه' : 'پروژه جدید'"
      :saving="saving"
      :error="error"
      @close="creating = false; editing = null"
      @save="save"
    >
      <div class="space-y-3">
        <div>
          <label class="office-label">نام پروژه</label>
          <input v-model="form.name" class="office-input" />
        </div>
        <div>
          <label class="office-label">توضیح</label>
          <textarea v-model="form.description" class="office-input" rows="3"></textarea>
        </div>
        <div class="grid sm:grid-cols-2 gap-3">
          <div>
            <label class="office-label">مدیر پروژه</label>
            <PickerField
              v-model="form.owner"
              :options="people.map((p) => ({ value: p.id, label: p.name }))"
              placeholder="انتخاب کنید…" clearable
            />
          </div>
          <div>
            <label class="office-label">مهلت</label>
            <JalaliDateField v-model="form.due_on" placeholder="بدون مهلت" />
          </div>
        </div>
        <div>
          <label class="office-label">رنگ پروژه</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="c in COLORS" :key="c"
              class="w-7 h-7 rounded-full transition-transform"
              :class="form.color === c ? 'ring-2 ring-offset-2 ring-slate-400 scale-110' : ''"
              :style="{ background: c }"
              :aria-label="`رنگ ${c}`"
              @click="form.color = c"
            ></button>
          </div>
        </div>

        <div>
          <label class="office-label">اعضا</label>
          <PeoplePicker v-model="form.member_ids" :people="people" />
          <p class="text-[11px] text-slate-400 mt-1">
            مدیر پروژه و سازنده همیشه عضو می‌مانند.
          </p>
        </div>
      </div>
    </FormModal>
  </div>
</template>
