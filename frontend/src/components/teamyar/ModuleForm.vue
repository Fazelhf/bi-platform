<script setup lang="ts">
/** افزودن / ویرایش ماژول — the charter's twelve are seeded; the rest are added here. */
import { reactive, ref } from "vue";
import { teamyarApi, type Module } from "@/api/teamyar";
import { apiError } from "@/components/crm/formError";
import FormModal from "@/components/crm/FormModal.vue";
import JalaliDateField from "@/components/JalaliDateField.vue";

const props = defineProps<{ module?: Module | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const m = props.module;
const form = reactive({
  title: m?.title ?? "",
  owner: m?.owner ?? "",
  specialist: m?.specialist ?? "",
  keywords: m?.keywords ?? "",
  starts_on: m?.starts_on ?? "",
  ends_on: m?.ends_on ?? "",
  in_scope: m?.in_scope ?? true,
});
const saving = ref(false);
const error = ref("");

async function save() {
  if (!form.title.trim()) { error.value = "نام ماژول را بنویسید."; return; }
  saving.value = true;
  error.value = "";
  try {
    const body = { ...form, starts_on: form.starts_on || null, ends_on: form.ends_on || null };
    if (m) await teamyarApi.modules.update(m.id, body);
    else await teamyarApi.modules.create(body);
    emit("saved");
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!m || !confirm(`ماژول «${m.title}» حذف شود؟\nفعالیت‌ها و جلساتش حذف نمی‌شوند و «عمومی» می‌شوند.`)) return;
  saving.value = true;
  try {
    await teamyarApi.modules.remove(m.id);
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
    :title="m ? 'ویرایش ماژول' : 'ماژول جدید'"
    :saving="saving" :error="error" :can-delete="!!m"
    @close="emit('close')" @save="save" @delete="remove"
  >
    <div class="space-y-3">
      <div>
        <label class="block text-xs text-slate-500 mb-1">نام ماژول</label>
        <input v-model="form.title" :class="inp" placeholder="مثلاً: پست و پیامک" />
      </div>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">مسئول داخلی</label>
          <input v-model="form.owner" :class="inp" placeholder="از کاغذ حساس نمابر" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">متخصص تیمیار</label>
          <input v-model="form.specialist" :class="inp" placeholder="مشاور تیمیار" />
        </div>
      </div>
      <div>
        <label class="block text-xs text-slate-500 mb-1">کلمات کلیدی</label>
        <textarea v-model="form.keywords" rows="2" :class="inp" placeholder="با ویرگول جدا کنید — مثلاً: پیامک، پنل پیامکی، ایمیل سازمانی"></textarea>
        <p class="text-[11px] text-slate-400 mt-1">
          فعالیت یا جلسه‌ای که در عنوانش نام ماژول یا یکی از این کلمه‌ها باشد خودکار زیر این ماژول می‌رود.
        </p>
      </div>
      <div class="grid sm:grid-cols-2 gap-3">
        <div>
          <label class="block text-xs text-slate-500 mb-1">شروع طبق برنامه (اختیاری)</label>
          <JalaliDateField v-model="form.starts_on" />
        </div>
        <div>
          <label class="block text-xs text-slate-500 mb-1">پایان طبق برنامه (اختیاری)</label>
          <JalaliDateField v-model="form.ends_on" />
        </div>
      </div>
      <label class="flex items-center gap-2 text-sm text-ink">
        <input v-model="form.in_scope" type="checkbox" class="accent-emerald-500" />
        در «پیشرفت کل» پروژه حساب شود
      </label>
    </div>
  </FormModal>
</template>
