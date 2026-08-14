<script setup lang="ts">
/**
 * ثبت / ویرایش وظیفه.
 *
 * Assignee defaults to nobody in the form and to *you* on the server. Most
 * tasks are somebody writing down their own work, and making them pick their
 * own name first is friction on the most common path.
 */
import { onMounted, ref } from "vue";
import { officeApi, type Person } from "@/api/office";
import { workApi, type Project, type Task, type TaskTag } from "@/api/officeWork";
import api from "@/api/client";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";

const props = defineProps<{
  task?: Task | null;
  /** Pre-selected when adding from inside a project. */
  projectId?: number | null;
}>();

const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const people = ref<Person[]>([]);
const projects = ref<Project[]>([]);
const tags = ref<TaskTag[]>([]);
const newTag = ref("");
const saving = ref(false);
const error = ref("");

const PRIORITIES = [
  { value: "low", label: "کم" },
  { value: "normal", label: "عادی" },
  { value: "high", label: "زیاد" },
  { value: "urgent", label: "فوری" },
];

const form = ref({
  title: "",
  description: "",
  project: (props.projectId ?? null) as number | null,
  assignee: null as number | null,
  due_on: "",
  priority: "normal",
  tags: [] as number[],
});

onMounted(async () => {
  const [p, pr, tg] = await Promise.all([
    officeApi.people().catch(() => ({ people: [] as Person[] })),
    workApi.projects().catch(() => [] as Project[]),
    api.get("/office/task-tags/").then((r) => r.data.results ?? r.data).catch(() => []),
  ]);
  people.value = p.people;
  projects.value = pr;
  tags.value = tg;

  if (props.task) {
    form.value = {
      title: props.task.title,
      description: props.task.description,
      project: props.task.project,
      assignee: props.task.assignee,
      due_on: props.task.due_on ?? "",
      priority: props.task.priority,
      tags: props.task.tags_detail.map((t) => t.id),
    };
  }
});

/**
 * Labels are data, and they get invented mid-thought — «فوری-انبار» while
 * writing the task that needs it. Creating one from a settings page nobody
 * opens means the field stays empty and the feature goes unused.
 */
async function addTag() {
  const name = newTag.value.trim();
  if (!name) return;
  const existing = tags.value.find((t) => t.name_fa === name);
  if (existing) {
    if (!form.value.tags.includes(existing.id)) form.value.tags.push(existing.id);
    newTag.value = "";
    return;
  }
  const { data } = await api.post("/office/task-tags/", { name_fa: name });
  tags.value.push(data);
  form.value.tags.push(data.id);
  newTag.value = "";
}

async function save() {
  if (!form.value.title.trim()) {
    error.value = "عنوان وظیفه را بنویسید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const body = { ...form.value, due_on: form.value.due_on || null };
    await workApi.saveTask(body as never, props.task?.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!props.task) return;
  saving.value = true;
  try {
    await workApi.removeTask(props.task.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <FormModal
    :title="task ? 'ویرایش وظیفه' : 'وظیفه جدید'"
    :saving="saving"
    :error="error"
    :can-delete="!!task"
    @close="emit('close')"
    @save="save"
    @delete="remove"
  >
    <div class="space-y-3">
      <div>
        <label class="block text-xs text-slate-500 mb-1">عنوان</label>
        <input v-model="form.title" :class="inp" placeholder="چه کاری باید انجام شود؟" />
      </div>

      <div>
        <label class="block text-xs text-slate-500 mb-1">توضیح</label>
        <textarea v-model="form.description" :class="inp" rows="3"></textarea>
      </div>

      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">مسئول</label>
          <PickerField
            v-model="form.assignee"
            :options="people.map((p) => ({ value: p.id, label: p.name, hint: p.job_title_fa }))"
            placeholder="خودم"
            hint="خالی یعنی خودتان"
            clearable
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">پروژه</label>
          <PickerField
            v-model="form.project"
            :options="projects.map((p) => ({ value: p.id, label: p.name }))"
            placeholder="بدون پروژه"
            clearable
          />
        </div>
      </div>

      <div>
        <label class="block text-xs text-slate-500 mb-1">برچسب‌ها</label>
        <div class="flex flex-wrap gap-1.5 mb-2">
          <button
            v-for="t in tags" :key="t.id"
            class="text-xs rounded-full px-3 py-1 transition-colors"
            :class="form.tags.includes(t.id)
              ? 'bg-panel text-white'
              : 'bg-slate-100 text-slate-500 hover:bg-slate-200'"
            @click="form.tags.includes(t.id)
              ? form.tags = form.tags.filter((x) => x !== t.id)
              : form.tags.push(t.id)"
          >{{ t.name_fa }}</button>
        </div>
        <input
          v-model="newTag" :class="inp" placeholder="برچسب تازه… (Enter)"
          @keydown.enter.prevent="addTag"
        />
      </div>

      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">مهلت</label>
          <input v-model="form.due_on" type="date" :class="inp" dir="ltr" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">اولویت</label>
          <select v-model="form.priority" :class="inp">
            <option v-for="p in PRIORITIES" :key="p.value" :value="p.value">
              {{ p.label }}
            </option>
          </select>
        </div>
      </div>
    </div>
  </FormModal>
</template>
