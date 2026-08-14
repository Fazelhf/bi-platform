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
import { workApi, type Project, type Task } from "@/api/officeWork";
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
});

onMounted(async () => {
  const [p, pr] = await Promise.all([
    officeApi.people().catch(() => ({ people: [] as Person[] })),
    workApi.projects().catch(() => [] as Project[]),
  ]);
  people.value = p.people;
  projects.value = pr;

  if (props.task) {
    form.value = {
      title: props.task.title,
      description: props.task.description,
      project: props.task.project,
      assignee: props.task.assignee,
      due_on: props.task.due_on ?? "",
      priority: props.task.priority,
    };
  }
});

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
