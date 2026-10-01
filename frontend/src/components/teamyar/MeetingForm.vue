<script setup lang="ts">
/** ثبت / ویرایش جلسه — برنامه، صورت‌جلسه، مصوبات و امتیاز اثربخشی. */
import { reactive, ref } from "vue";
import {
  MEETING_KINDS, MEETING_STATUSES, teamyarApi, toLocalInput,
  type Meeting, type Module, type TeamyarTask,
} from "@/api/teamyar";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import AttendeesPicker from "@/components/teamyar/AttendeesPicker.vue";
import PickerField from "@/components/PickerField.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";
import { todayIso } from "@/utils/jalali";

const props = defineProps<{ meeting?: Meeting | null; tasks: TeamyarTask[]; modules: Module[] }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const m = props.meeting;
const form = reactive({
  title: m?.title ?? "",
  kind: m?.kind ?? "vendor",
  status: m?.status ?? "planned",
  held_at: m ? toLocalInput(m.held_at) : `${todayIso()}T10:00`,
  duration_min: m?.duration_min ?? 60,
  attendees: m?.attendees ?? "",
  agenda: m?.agenda ?? "",
  summary: m?.summary ?? "",
  decisions: m?.decisions ?? "",
  rating: m?.rating ?? (null as number | null),
  task: m?.task ?? (null as number | null),
  module: m?.module ?? (null as number | null),
});
const MODULE_OPTIONS = props.modules.map((x) => ({ value: x.id, label: x.title }));
const saving = ref(false);
const error = ref("");

async function save() {
  saving.value = true;
  error.value = "";
  try {
    // No module chosen: the server reads it from the title, then the activity.
    const body = { ...form, rating: form.status === "held" ? form.rating : null };
    if (m) await teamyarApi.meetings.update(m.id, body);
    else await teamyarApi.meetings.create(body);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!m) return;
  saving.value = true;
  try {
    await teamyarApi.meetings.remove(m.id);
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
    :title="m ? 'ویرایش جلسه' : 'جلسه جدید'"
    :saving="saving" :error="error" :can-delete="!!m" wide
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="space-y-3">
      <div>
        <label class="block text-xs text-slate-500 mb-1">موضوع جلسه</label>
        <input v-model="form.title" :class="inp" placeholder="مثلاً: جلسه‌ی نیازسنجی واحد مالی" />
      </div>
      <div class="grid sm:grid-cols-3 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">نوع</label>
          <PickerField
            v-model="form.kind"
            :options="Object.entries(MEETING_KINDS).map(([value, label]) => ({ value, label }))"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">وضعیت</label>
          <PickerField
            v-model="form.status"
            :options="Object.entries(MEETING_STATUSES).map(([value, label]) => ({ value, label }))"
          />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">مدت (دقیقه)</label>
          <input v-model.number="form.duration_min" type="number" min="5" step="5" :class="inp" />
        </div>
      </div>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">زمان</label>
          <JalaliDateField v-model="form.held_at" with-time />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">فعالیت مرتبط</label>
          <PickerField
            v-model="form.task"
            :options="tasks.map((t) => ({ value: t.id, label: t.title }))"
            placeholder="—" clearable
          />
        </div>
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">ماژول</label>
        <PickerField
          v-model="form.module"
          :options="MODULE_OPTIONS"
          placeholder="خودکار از روی عنوان" clearable
        />
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">حاضرین</label>
        <AttendeesPicker v-model="form.attendees" />
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">دستور جلسه</label>
        <textarea v-model="form.agenda" :class="inp" rows="2"></textarea>
      </div>
      <template v-if="form.status === 'held'">
        <div>
          <label class="block text-xs text-slate-500 mb-1">خلاصه‌ی مذاکرات</label>
          <textarea v-model="form.summary" :class="inp" rows="3"></textarea>
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">مصوبات و اقدامات</label>
          <textarea v-model="form.decisions" :class="inp" rows="3" placeholder="هر مصوبه در یک خط"></textarea>
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">اثربخشی جلسه</label>
          <div class="flex gap-1" dir="ltr">
            <button
              v-for="n in 5" :key="n" type="button"
              class="text-2xl leading-none"
              :class="(form.rating ?? 0) >= n ? 'text-amber-400' : 'text-slate-300'"
              @click="form.rating = form.rating === n ? null : n"
            >★</button>
          </div>
        </div>
      </template>
    </div>
  </FormModal>
</template>
