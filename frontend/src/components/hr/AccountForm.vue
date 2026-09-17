<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import { apiError } from "@/components/crm/formError";
import { hrApi, type Account, type Person } from "@/api/hr";

/**
 * حساب کاربری برای یک فرد — admin only, two ways.
 *
 * * **ساخت حساب جدید** — the server builds it with the admin panel's own user
 *   serializer, so the password policy is the same one «کاربر جدید» there
 *   enforces.
 * * **وصل کردن حساب موجود** — for someone who already signs in, with an
 *   account made in the admin panel before they were on the chart. A second
 *   login would split their records between two accounts.
 *
 * Either way the account is attached to the person in the same save, which is
 * what makes their CRM and sales records belong to whoever signs in.
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

const mode = ref<"create" | "link">("create");
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

// ---- link an existing account -------------------------------------------------
const accounts = ref<Account[]>([]);
const linkUser = ref<number | null>(null);

/** Spelling aside, is this account plausibly the same person? */
const normal = (s: string) => s.replace(/[\s‌]+/g, "").replace(/ي/g, "ی").replace(/ك/g, "ک");

/** Accounts already attached to someone are listed, but cannot be picked. */
const linkOptions = computed(() => accounts.value.map((a) => ({
  value: a.id,
  label: a.name,
  hint: a.linked_to ? `وصل به ${a.linked_to}` : a.username,
  disabled: !!a.linked_to,
})));
const freeCount = computed(() => accounts.value.filter((a) => !a.linked_to).length);
const chosen = computed(() => accounts.value.find((a) => a.id === linkUser.value) ?? null);

onMounted(async () => {
  try {
    accounts.value = await hrApi.accounts();
  } catch {
    accounts.value = [];
  }
  // An unlinked account under this person's own name is almost certainly
  // theirs — offer it rather than making the admin search for it.
  const same = accounts.value.filter(
    (a) => !a.linked_to && normal(a.name) === normal(props.person.full_name_fa),
  );
  if (same.length === 1) {
    linkUser.value = same[0].id;
    mode.value = "link";
  }
});

async function save() {
  error.value = "";
  if (mode.value === "link") {
    if (!linkUser.value) {
      error.value = "حساب کاربری را انتخاب کنید.";
      return;
    }
    saving.value = true;
    try {
      emit("saved", await hrApi.linkAccount(props.person.id, linkUser.value));
    } catch (e) {
      error.value = apiError(e);
    } finally {
      saving.value = false;
    }
    return;
  }

  if (!form.value.username.trim() || !form.value.password) {
    error.value = "نام کاربری و رمز عبور الزامی است.";
    return;
  }
  saving.value = true;
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
    title="حساب کاربری"
    :subtitle="person.full_name_fa"
    :saving="saving"
    :error="error"
    :save-label="mode === 'link' ? 'وصل کردن حساب' : 'ساخت حساب'"
    @close="emit('close')"
    @save="save"
  >
    <div class="flex bg-slate-100 rounded-xl p-1 text-sm">
      <button
        type="button"
        class="flex-1 rounded-lg py-1.5 transition"
        :class="mode === 'create' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-500'"
        @click="mode = 'create'"
      >ساخت حساب جدید</button>
      <button
        type="button"
        class="flex-1 rounded-lg py-1.5 transition"
        :class="mode === 'link' ? 'bg-surface shadow-sm text-ink font-medium' : 'text-slate-500'"
        @click="mode = 'link'"
      >وصل کردن حساب موجود</button>
    </div>

    <!-- Link an account that already exists -->
    <template v-if="mode === 'link'">
      <div>
        <label :class="lbl">حساب کاربری موجود</label>
        <PickerField
          v-model="linkUser" :options="linkOptions"
          placeholder="— یک حساب را انتخاب کنید" search-placeholder="نام یا نام کاربری…"
        />
      </div>
      <p v-if="chosen" class="text-xs text-slate-500">
        «{{ chosen.name }}» با نام کاربری <span class="ltr-nums font-medium">{{ chosen.username }}</span>
        به {{ person.full_name_fa }} وصل می‌شود؛ رمز و دسترسی‌هایش تغییری نمی‌کند.
      </p>
      <p v-else-if="!freeCount" class="text-xs text-amber-600">
        همهٔ حساب‌های فعال به فرد دیگری وصل‌اند — اگر حساب جدیدی لازم است، «ساخت حساب جدید» را انتخاب کنید.
      </p>
      <p class="text-xs text-slate-400">
        برای کسی که از قبل در سامانه حساب دارد: سوابق CRM و فروش این فرد به همان حساب نسبت داده می‌شود.
        حسابی که به فرد دیگری وصل است قابل انتخاب نیست.
      </p>
    </template>

    <!-- Make a new account -->
    <template v-else>
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
    </template>
  </FormModal>
</template>
