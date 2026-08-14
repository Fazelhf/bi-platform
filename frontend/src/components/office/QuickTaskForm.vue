<script setup lang="ts">
/**
 * ثبت سریع وظیفه — one field, and everything else behind a chip.
 *
 * The modal it replaces asked seven labelled questions to record «فردا با
 * انبار تماس بگیر». Most tasks have a title and nothing else, so the form
 * that fits most tasks is a title and nothing else; the other six controls
 * are chips that open only when the answer is «yes, that one matters».
 *
 * Inline rather than a dialog, for the same reason: a modal is a context
 * switch, and writing something down should not be one. The list stays
 * visible behind it, so you can see you are not repeating yourself.
 *
 * Editing still uses the full form. That is a different act — you are
 * reviewing every field, not capturing a thought.
 */
import { computed, onMounted, ref } from "vue";
import { officeApi, type Person } from "@/api/office";
import { workApi, type Project, type TaskTag } from "@/api/officeWork";
import api from "@/api/client";
import { apiError } from "@/components/crm/formError";
import { faDate } from "@/utils/adminFormat";
import PickerField from "@/components/PickerField.vue";

const props = defineProps<{
  /** Pre-selected when adding from inside a project. */
  projectId?: number | null;
  /** Pre-selected category, when adding into a column. */
  groupId?: number | null;
}>();

const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const people = ref<Person[]>([]);
const projects = ref<Project[]>([]);
const tags = ref<TaskTag[]>([]);
const saving = ref(false);
const error = ref("");
const titleEl = ref<HTMLInputElement | null>(null);

/** Which optional controls the user has asked to see. */
const open = ref({ desc: false, due: false, who: false, project: false, tags: false });

const form = ref({
  title: "",
  description: "",
  project: (props.projectId ?? null) as number | null,
  group: (props.groupId ?? null) as number | null,
  assignee: null as number | null,
  due_on: "",
  priority: "normal",
  tags: [] as number[],
});

const PRIORITIES = [
  { value: "low", label: "کم" },
  { value: "normal", label: "عادی" },
  { value: "high", label: "زیاد" },
  { value: "urgent", label: "فوری" },
];

onMounted(async () => {
  titleEl.value?.focus();
  const [p, pr, tg] = await Promise.all([
    officeApi.people().catch(() => ({ people: [] as Person[] })),
    workApi.projects().catch(() => [] as Project[]),
    api.get("/office/task-tags/").then((r) => r.data.results ?? r.data).catch(() => []),
  ]);
  people.value = p.people;
  projects.value = pr;
  tags.value = tg;
});

/** Today and tomorrow as one tap each — the two dates people actually pick. */
function setDue(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  form.value.due_on = d.toISOString().slice(0, 10);
  open.value.due = true;
}

const assigneeName = computed(() => {
  const p = people.value.find((x) => x.id === form.value.assignee);
  return p ? p.name : "خودم";
});

const projectName = computed(() => {
  const p = projects.value.find((x) => x.id === form.value.project);
  return p ? p.name : "بدون پروژه";
});

async function save() {
  if (!form.value.title.trim()) {
    error.value = "عنوان وظیفه را بنویسید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    await workApi.saveTask({
      ...form.value,
      due_on: form.value.due_on || null,
    } as never);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

const chip =
  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition-colors";
const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 space-y-3">
    <!-- The one thing every task has. Enter saves; Escape gives up. -->
    <input
      ref="titleEl"
      v-model="form.title"
      class="w-full bg-transparent border-b-2 pb-2 text-sm text-ink outline-none
             placeholder:text-slate-400 transition-colors"
      :style="{ borderColor: form.title ? 'var(--sec-solid)' : 'rgb(var(--c-slate-200))' }"
      placeholder="چه کاری باید انجام شود؟"
      @keydown.enter.prevent="save"
      @keydown.esc="emit('close')"
    />

    <!-- Chips. A filled one shows its value, so the row doubles as a summary. -->
    <div class="flex flex-wrap items-center gap-1.5">
      <button
        :class="[chip, open.desc || form.description
          ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100']"
        @click="open.desc = !open.desc"
      >توضیحات</button>

      <button
        :class="[chip, form.due_on ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100']"
        @click="open.due = !open.due"
      >
        {{ form.due_on ? faDate(form.due_on) : "بدون مهلت" }}
      </button>
      <button v-if="!form.due_on" :class="[chip, 'text-slate-400 hover:bg-slate-100']" @click="setDue(0)">
        امروز
      </button>
      <button v-if="!form.due_on" :class="[chip, 'text-slate-400 hover:bg-slate-100']" @click="setDue(1)">
        فردا
      </button>

      <button
        :class="[chip, form.assignee ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100']"
        @click="open.who = !open.who"
      >مسئول: {{ assigneeName }}</button>

      <button
        v-if="!projectId"
        :class="[chip, form.project ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100']"
        @click="open.project = !open.project"
      >{{ projectName }}</button>

      <button
        :class="[chip, form.tags.length ? 'bg-slate-100 text-ink' : 'text-slate-500 hover:bg-slate-100']"
        @click="open.tags = !open.tags"
      >
        برچسب<span v-if="form.tags.length" class="ltr-nums"> ({{ form.tags.length }})</span>
      </button>

      <select
        v-model="form.priority"
        class="text-xs bg-transparent text-slate-500 outline-none rounded-lg px-1 py-1.5"
      >
        <option v-for="p in PRIORITIES" :key="p.value" :value="p.value">
          اولویت {{ p.label }}
        </option>
      </select>
    </div>

    <!-- Only what was asked for -->
    <textarea
      v-if="open.desc"
      v-model="form.description" :class="inp" rows="2" placeholder="توضیح بیشتر…"
    ></textarea>

    <input v-if="open.due" v-model="form.due_on" type="date" :class="inp" dir="ltr" />

    <PickerField
      v-if="open.who"
      v-model="form.assignee"
      :options="people.map((p) => ({ value: p.id, label: p.name, hint: p.job_title_fa }))"
      placeholder="خودم" hint="خالی یعنی خودتان" clearable
    />

    <PickerField
      v-if="open.project && !projectId"
      v-model="form.project"
      :options="projects.map((p) => ({ value: p.id, label: p.name }))"
      placeholder="بدون پروژه" clearable
    />

    <div v-if="open.tags" class="flex flex-wrap gap-1.5">
      <button
        v-for="t in tags" :key="t.id"
        class="text-xs rounded-full px-3 py-1 transition-colors"
        :class="form.tags.includes(t.id)
          ? 'bg-panel text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
        @click="form.tags.includes(t.id)
          ? form.tags = form.tags.filter((x) => x !== t.id)
          : form.tags.push(t.id)"
      >{{ t.name_fa }}</button>
      <span v-if="!tags.length" class="text-xs text-slate-400">
        هنوز برچسبی ساخته نشده — از فرم کامل ویرایش می‌توانید بسازید.
      </span>
    </div>

    <p v-if="error" class="text-red-600 text-xs">{{ error }}</p>

    <div class="flex items-center gap-2">
      <button class="office-btn rounded-xl px-4 py-2 text-sm" :disabled="saving" @click="save">
        {{ saving ? "…" : "ایجاد" }}
      </button>
      <button class="text-sm text-slate-500 px-3 py-2" @click="emit('close')">انصراف</button>
      <span class="text-[11px] text-slate-400 mr-auto">Enter برای ثبت</span>
    </div>
  </div>
</template>
