<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { hrApi, type Account, type Person } from "@/api/hr";

/** افزودن / ویرایش فرد. */
const props = defineProps<{ person?: Person | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const accounts = ref<Account[]>([]);
const saving = ref(false);
const error = ref("");
const duplicate = ref<Person | null>(null);

const form = ref({
  full_name_fa: props.person?.full_name_fa ?? "",
  mobile: props.person?.mobile ?? "",
  hired_on: props.person?.hired_on ?? "",
  user: props.person?.user ?? (null as number | null),
  note: props.person?.note ?? "",
});

/** An account already attached to someone else is shown but cannot be taken. */
const accountOptions = computed(() => accounts.value.map((a) => ({
  value: a.id,
  label: a.name,
  hint: a.linked_to && a.linked_to !== props.person?.full_name_fa
    ? `وصل به ${a.linked_to}`
    : a.username,
  disabled: !!a.linked_to && a.id !== props.person?.user,
})));

onMounted(async () => {
  accounts.value = await hrApi.accounts();
});

async function save(force = false) {
  if (!form.value.full_name_fa.trim()) {
    error.value = "نام الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const payload: Record<string, unknown> = { ...form.value, force };
    if (!payload.hired_on) payload.hired_on = null;
    await hrApi.savePerson(payload, props.person?.id);
    emit("saved");
  } catch (e: any) {
    if (e?.response?.status === 409) {
      duplicate.value = e.response.data.duplicate;
    } else {
      error.value = apiError(e);
    }
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    :title="person ? 'ویرایش فرد' : 'فرد جدید'"
    :subtitle="person?.full_name_fa"
    :saving="saving"
    :error="error"
    @close="emit('close')"
    @save="save()"
  >
    <div>
      <label :class="lbl">نام و نام خانوادگی *</label>
      <input v-model="form.full_name_fa" :class="inp" />
    </div>

    <div v-if="duplicate" class="text-sm bg-amber-50 text-amber-700 rounded-xl p-3 space-y-2">
      <p>
        «{{ duplicate.full_name_fa }}» با همین نام قبلا ثبت شده
        <template v-if="!duplicate.is_active"> و در بایگانی است — به‌جای ثبت دوباره، از بایگانی بازگردانید</template>.
      </p>
      <button class="text-xs underline" @click="save(true)">فرد دیگری است، ثبت کن</button>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">موبایل</label>
        <input v-model="form.mobile" :class="inp" dir="ltr" inputmode="tel" />
      </div>
      <div>
        <label :class="lbl">تاریخ شروع همکاری</label>
        <input v-model="form.hired_on" :class="inp" type="date" dir="ltr" />
      </div>
    </div>

    <div>
      <label :class="lbl">حساب کاربری سامانه</label>
      <PickerField
        v-model="form.user" :options="accountOptions"
        placeholder="— بدون حساب" search-placeholder="نام کاربری…"
      />
      <p class="text-xs text-slate-400 mt-1">
        وصل کردن حساب یعنی سوابق CRM و فروش این فرد به همان کسی نسبت داده می‌شود که وارد سامانه می‌شود.
      </p>
    </div>

    <div>
      <label :class="lbl">توضیحات</label>
      <textarea v-model="form.note" :class="inp" rows="2" />
    </div>
  </FormModal>
</template>
