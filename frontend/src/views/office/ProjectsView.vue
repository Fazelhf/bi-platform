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
import { faDate } from "@/utils/adminFormat";
import FormModal from "@/components/crm/FormModal.vue";
import PeoplePicker from "@/components/office/PeoplePicker.vue";
import PickerField from "@/components/PickerField.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

const router = useRouter();

const projects = ref<Project[]>([]);
const people = ref<Person[]>([]);
const loading = ref(true);
const error = ref("");
const editing = ref<Project | null>(null);
const creating = ref(false);
const saving = ref(false);
const search = ref("");

const form = ref({
  name: "", description: "", owner: null as number | null,
  due_on: "", member_ids: [] as number[],
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
  form.value = { name: "", description: "", owner: null, due_on: "", member_ids: [] };
  creating.value = true;
}

function startEdit(p: Project) {
  form.value = {
    name: p.name, description: p.description, owner: p.owner,
    due_on: p.due_on ?? "",
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

/** Green when finished, amber while anything is late, otherwise neutral. */
function barClass(p: Project): string {
  if (p.progress_pct >= 100) return "bg-emerald-500";
  if (p.overdue_count) return "bg-amber-500";
  return "bg-panel";
}

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="startNew">
        + پروژه جدید
      </button>
      <input
        v-model="search" :class="inp" class="flex-1 min-w-[12rem]"
        placeholder="جستجوی نام پروژه…"
      />
      <span class="text-xs text-slate-400 ltr-nums">{{ num(shown.length) }} پروژه</span>
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

    <div v-else class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      <!--
        The whole card opens the project.

        Before this, only the title text was a button — about a fifth of a
        151px card — so clicking anywhere else did nothing and the project
        «could not be opened». A card that looks like one target must be one
        target; ویرایش sits above it and stops the click from reaching it.
      -->
      <div
        v-for="p in shown" :key="p.id"
        class="relative bg-surface rounded-card shadow-soft hover:shadow-pop
               transition-shadow"
      >
        <button
          class="w-full text-right p-4 flex flex-col gap-3 rounded-card"
          @click="router.push({ name: 'office-project', params: { id: p.id } })"
        >
          <span class="block min-w-0 w-full pl-14">
            <span class="block font-bold text-ink text-sm truncate">{{ p.name }}</span>
            <span v-if="p.due_on" class="block text-[11px] text-slate-400 mt-0.5 ltr-nums">
              مهلت {{ faDate(p.due_on) }}
            </span>
          </span>

        <span class="block w-full">
          <span class="flex items-baseline justify-between text-xs mb-1">
            <span class="text-slate-500">وضعیت کل پروژه</span>
            <span class="text-ink ltr-nums">{{ num(p.progress_pct) }}٪</span>
          </span>
          <span class="block h-2 bg-slate-100 rounded-full overflow-hidden">
            <span
              class="block h-full rounded-full transition-all"
              :class="barClass(p)"
              :style="{ width: `${Math.max(p.progress_pct, 1)}%` }"
            ></span>
          </span>
          <span class="block text-[11px] text-slate-400 mt-1 ltr-nums">
            {{ num(p.done_count) }} از {{ num(p.task_count) }} وظیفه
            <span v-if="p.overdue_count" class="text-amber-600">
              · {{ num(p.overdue_count) }} عقب‌افتاده
            </span>
          </span>
        </span>

        <span class="flex items-center justify-between gap-2 w-full mt-auto">
          <span class="flex -space-x-2 space-x-reverse">
            <UserAvatar
              v-for="m in p.memberships.slice(0, 5)" :key="m.id"
              :user="m.user_detail as any" :size="26" :title="m.user_detail.name"
              class="ring-2 ring-surface rounded-full"
            />
            <span
              v-if="p.memberships.length > 5"
              class="w-[26px] h-[26px] rounded-full bg-slate-100 text-[10px] text-slate-500
                     grid place-items-center ring-2 ring-surface ltr-nums"
            >+{{ num(p.memberships.length - 5) }}</span>
          </span>
          <span
            class="text-[11px] rounded-full px-2 py-1 ltr-nums"
            :class="p.my_open_count ? 'bg-slate-100 text-slate-600' : 'text-slate-300'"
          >{{ num(p.my_open_count) }} کار من</span>
        </span>
        </button>

        <!-- Layered over the card, so it does not open the project too. -->
        <button
          class="absolute top-3 left-3 text-xs text-slate-400 hover:text-ink
                 bg-surface/80 rounded-lg px-2 py-1"
          @click.stop="startEdit(p)"
        >ویرایش</button>
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
          <label class="block text-xs text-slate-500 mb-1">نام پروژه</label>
          <input v-model="form.name" :class="inp" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">توضیح</label>
          <textarea v-model="form.description" :class="inp" rows="3"></textarea>
        </div>
        <div class="grid sm:grid-cols-2 gap-3">
          <div>
            <label class="block text-xs text-slate-500 mb-1">مدیر پروژه</label>
            <PickerField
              v-model="form.owner"
              :options="people.map((p) => ({ value: p.id, label: p.name }))"
              placeholder="انتخاب کنید…" clearable
            />
          </div>
          <div>
            <label class="block text-xs text-slate-500 mb-1">مهلت</label>
            <input v-model="form.due_on" type="date" :class="inp" dir="ltr" />
          </div>
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">اعضا</label>
          <PeoplePicker v-model="form.member_ids" :people="people" />
          <p class="text-[11px] text-slate-400 mt-1">
            مدیر پروژه و سازنده همیشه عضو می‌مانند.
          </p>
        </div>
      </div>
    </FormModal>
  </div>
</template>
