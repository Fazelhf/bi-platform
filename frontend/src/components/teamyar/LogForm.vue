<script setup lang="ts">
/** ثبت رویداد: تماس، پیام، مشکل، تصمیم… */
import { reactive, ref } from "vue";
import { LOG_KINDS, teamyarApi, toLocalInput, type LogEntry, type TeamyarTask } from "@/api/teamyar";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";

const props = defineProps<{ entry?: LogEntry | null; tasks: TeamyarTask[] }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const l = props.entry;
const form = reactive({
  happened_at: toLocalInput(l?.happened_at ?? new Date().toISOString()),
  kind: l?.kind ?? "call",
  counterpart: l?.counterpart ?? "",
  subject: l?.subject ?? "",
  body: l?.body ?? "",
  resolved: l?.resolved ?? false,
  task: l?.task ?? (null as number | null),
});
const saving = ref(false);
const error = ref("");

async function save() {
  saving.value = true;
  error.value = "";
  try {
    if (l) await teamyarApi.logs.update(l.id, form);
    else await teamyarApi.logs.create(form);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!l) return;
  saving.value = true;
  try {
    await teamyarApi.logs.remove(l.id);
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
    :title="l ? 'ویرایش رویداد' : 'ثبت رویداد / مکالمه'"
    :saving="saving" :error="error" :can-delete="!!l"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="space-y-3">
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">نوع</label>
          <PickerField
            v-model="form.kind"
            :options="Object.entries(LOG_KINDS).map(([value, label]) => ({ value, label }))"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">زمان</label>
          <JalaliDateField v-model="form.happened_at" with-time />
        </div>
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">موضوع</label>
        <input v-model="form.subject" :class="inp" placeholder="در یک جمله چه شد؟" />
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">طرف گفتگو</label>
        <input v-model="form.counterpart" :class="inp" placeholder="مثلاً: آقای … از تیمیار" />
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">شرح کامل</label>
        <textarea v-model="form.body" :class="inp" rows="4" placeholder="چه گفته شد، چه قولی داده شد…"></textarea>
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">فعالیت مرتبط</label>
        <PickerField
          v-model="form.task"
          :options="tasks.map((t) => ({ value: t.id, label: t.title }))"
          placeholder="—" clearable
        />
      </div>
      <label v-if="form.kind === 'issue'" class="flex items-center gap-2 text-sm text-ink">
        <input v-model="form.resolved" type="checkbox" class="accent-emerald-500" />
        مشکل برطرف شد
      </label>
    </div>
  </FormModal>
</template>
