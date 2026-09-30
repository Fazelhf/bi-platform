<script setup lang="ts">
/** ثبت / ویرایش فعالیت گانت. */
import { reactive, ref } from "vue";
import { STATUS_LABELS, teamyarApi, type Phase, type TeamyarTask } from "@/api/teamyar";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import { todayIso } from "@/utils/jalali";

const props = defineProps<{ task?: TeamyarTask | null; phases: Phase[]; tasks: TeamyarTask[] }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const t = props.task;
const form = reactive({
  title: t?.title ?? "",
  description: t?.description ?? "",
  phase: t?.phase ?? (null as number | null),
  owner: t?.owner ?? "",
  start_on: t?.start_on ?? todayIso(),
  end_on: t?.end_on ?? todayIso(),
  progress: t?.progress ?? 0,
  status: t?.status ?? "todo",
  is_milestone: t?.is_milestone ?? false,
  depends_on: t?.depends_on ?? (null as number | null),
});
const saving = ref(false);
const error = ref("");

async function save() {
  saving.value = true;
  error.value = "";
  try {
    const body = { ...form, progress: Number(form.progress) || 0 };
    if (form.is_milestone) body.start_on = form.end_on;
    if (t) await teamyarApi.tasks.update(t.id, body);
    else await teamyarApi.tasks.create(body);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!t) return;
  saving.value = true;
  try {
    await teamyarApi.tasks.remove(t.id);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
    saving.value = false;
  }
}

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none " +
  "focus:ring-2 focus:ring-slate-300";
</script>

<template>
  <FormModal
    :title="t ? 'ویرایش فعالیت' : 'فعالیت جدید'"
    :saving="saving" :error="error" :can-delete="!!t"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="space-y-3">
      <div>
        <label class="block text-xs text-slate-500 mb-1">عنوان</label>
        <input v-model="form.title" :class="inp" placeholder="مثلاً: نصب و پیکربندی سرور" />
      </div>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">فاز</label>
          <PickerField
            v-model="form.phase"
            :options="phases.map((p) => ({ value: p.id, label: p.title }))"
            placeholder="بدون فاز" clearable
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">مسئول</label>
          <input v-model="form.owner" :class="inp" placeholder="نام شخص یا تیم" />
        </div>
      </div>
      <label class="flex items-center gap-2 text-sm text-ink">
        <input v-model="form.is_milestone" type="checkbox" class="accent-amber-500" />
        نقطه‌ی عطف (Milestone) — یک تاریخ، بدون مدت
      </label>
      <div class="grid sm:grid-cols-2 gap-3">
        <div v-if="!form.is_milestone">
          <label class="block text-xs text-slate-500 mb-1">شروع</label>
          <JalaliDateField v-model="form.start_on" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">{{ form.is_milestone ? "تاریخ" : "پایان / ددلاین" }}</label>
          <JalaliDateField v-model="form.end_on" />
        </div>
      </div>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">وضعیت</label>
          <PickerField
            v-model="form.status"
            :options="Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">پیشرفت: {{ form.progress }}٪</label>
          <input v-model.number="form.progress" type="range" min="0" max="100" step="5" class="w-full mt-2" />
        </div>
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">وابسته به</label>
        <PickerField
          v-model="form.depends_on"
          :options="tasks.filter((x) => x.id !== t?.id).map((x) => ({ value: x.id, label: x.title }))"
          placeholder="هیچ‌کدام" clearable
        />
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">توضیح</label>
        <textarea v-model="form.description" :class="inp" rows="3"></textarea>
      </div>
    </div>
  </FormModal>
</template>
