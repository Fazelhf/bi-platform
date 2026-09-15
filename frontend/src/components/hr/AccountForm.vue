<script setup lang="ts">
import { ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { hrApi, type Person } from "@/api/hr";

/**
 * ساخت حساب کاربری برای یک فرد — admin only.
 *
 * The server builds it with the admin panel's own user serializer, so the
 * password policy is the same one «کاربر جدید» there enforces. The account is
 * attached to the person in the same save, which is what makes their CRM and
 * sales records belong to whoever signs in.
 */
const props = defineProps<{ person: Person }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved", p: Person): void }>();

const inp =
  "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";
const lbl = "text-xs text-slate-500 mb-1 block";

const ROLES = [
  { value: "operator", label: "کارشناس", hint: "ورود اطلاعات بخش خودش" },
  { value: "manager", label: "مدیر بخش", hint: "ورود و ارسال اطلاعات بخش" },
  { value: "viewer", label: "فقط مشاهده", hint: "داشبوردها، بدون ورود اطلاعات" },
  { value: "executive", label: "مدیریت", hint: "همه داشبوردها و تایید" },
];
const DEPARTMENTS = [
  { value: "", label: "— بدون بخش" },
  { value: "sales_team", label: "فروش همکار" },
  { value: "sales_org", label: "فروش بانکی" },
  { value: "sales_b2b", label: "فروش B2B" },
  { value: "production", label: "تولید" },
  { value: "finance", label: "مالی" },
  { value: "commercial", label: "بازرگانی" },
];

const saving = ref(false);
const error = ref("");
const showPassword = ref(false);

const form = ref({
  username: "",
  password: "",
  display_name_fa: props.person.full_name_fa,
  phone: props.person.mobile,
  role: "operator",
  department: "",
});

async function save() {
  if (!form.value.username.trim() || !form.value.password) {
    error.value = "نام کاربری و رمز عبور الزامی است.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const person = await hrApi.createAccount(props.person.id, {
      ...form.value,
      username: form.value.username.trim(),
    });
    emit("saved", person);
  } catch (e) {
    error.value = apiError(e);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    title="ساخت حساب کاربری"
    :subtitle="person.full_name_fa"
    :saving="saving"
    :error="error"
    save-label="ساخت حساب"
    @close="emit('close')"
    @save="save"
  >
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نام کاربری *</label>
        <input v-model="form.username" :class="inp" dir="ltr" autocomplete="off" placeholder="s.mousavi" />
      </div>
      <div>
        <label :class="lbl">رمز عبور *</label>
        <div class="relative">
          <input
            v-model="form.password" :class="inp" dir="ltr" autocomplete="new-password"
            :type="showPassword ? 'text' : 'password'"
          />
          <button
            type="button"
            class="absolute left-2 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-ink"
            @click="showPassword = !showPassword"
          >{{ showPassword ? "پنهان" : "نمایش" }}</button>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نام نمایشی</label>
        <input v-model="form.display_name_fa" :class="inp" />
      </div>
      <div>
        <label :class="lbl">موبایل</label>
        <input v-model="form.phone" :class="inp" dir="ltr" inputmode="tel" />
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div>
        <label :class="lbl">نقش</label>
        <PickerField v-model="form.role" :options="ROLES" :clearable="false" />
      </div>
      <div>
        <label :class="lbl">بخش ورود اطلاعات</label>
        <PickerField v-model="form.department" :options="DEPARTMENTS" :clearable="false" />
      </div>
    </div>

    <p class="text-xs text-slate-400">
      رمز عبور باید با سیاست رمز سامانه بخواند. نام کاربری و رمز را به خود فرد بدهید؛
      دسترسی‌های بیشتر از پنل ادمین تنظیم می‌شود.
    </p>
  </FormModal>
</template>
