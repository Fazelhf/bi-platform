<script setup lang="ts">
import { onMounted, ref } from "vue";
import CrudTable, { type CrudColumn } from "@/components/CrudTable.vue";
import { usersApi } from "@/api/platform";
import type { UserRow } from "@/types";

const rows = ref<UserRow[]>([]);
const loading = ref(true);
const error = ref("");

const columns: CrudColumn[] = [
  { key: "username", label: "نام کاربری", required: true },
  { key: "display_name_fa", label: "نام نمایشی" },
  {
    key: "role", label: "نقش", type: "select",
    options: [
      { value: "executive", label: "مدیرعامل (فقط مشاهده)" },
      { value: "manager", label: "مدیر بخش" },
      { value: "operator", label: "اپراتور" },
      { value: "viewer", label: "بیننده" },
    ],
  },
  {
    key: "department", label: "بخش", type: "select",
    options: [
      { value: "", label: "— بدون بخش" },
      { value: "production", label: "تولید" },
      { value: "sales_org", label: "فروش بانکی" },
      { value: "sales_team", label: "فروش همکار" },
      { value: "sales_b2b", label: "فروش B2B" },
    ],
  },
  { key: "is_active", label: "فعال", type: "boolean" },
  { key: "phone", label: "موبایل", type: "text" },
  // Only ever unticked here: enabling belongs to the user, who proves the
  // number is theirs by entering a code sent to it. The API refuses a tick
  // with that explanation, so this column is the "lost the phone" switch.
  { key: "two_factor_enabled", label: "ورود دو مرحله‌ای", type: "boolean" },
  { key: "password", label: "رمز عبور (برای تغییر، خالی نگذارید)", type: "password", showInTable: false },
];

async function load() {
  loading.value = true;
  try {
    rows.value = await usersApi.list();
  } finally {
    loading.value = false;
  }
}

async function run(op: () => Promise<unknown>) {
  error.value = "";
  try {
    await op();
    await load();
  } catch (e: any) {
    error.value = JSON.stringify(e?.response?.data ?? "خطا");
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-bold text-ink">مدیریت کاربران</h1>
    <p v-if="error" class="text-sm text-red-600 bg-red-50 rounded-lg p-2 ltr-nums">{{ error }}</p>
    <CrudTable
      title="کاربران سیستم"
      :columns="columns"
      :rows="rows"
      :loading="loading"
      @create="(p) => run(() => usersApi.create(p as any))"
      @update="(id, p) => run(() => usersApi.patch(id, p as any))"
      @remove="(id) => run(() => usersApi.remove(id))"
    />
    <p class="text-xs text-slate-400">
      نقش «مدیرعامل» همه داشبوردها را می‌بیند و تاییدکننده نهایی است ولی داده وارد
      نمی‌کند؛ «مدیر بخش» فقط بخش خودش را ورود و ارسال می‌کند.
    </p>
    <p class="text-xs text-slate-400">
      «ورود دو مرحله‌ای» را فقط می‌توانید <b>غیرفعال</b> کنید (برای کاربری که گوشی‌اش
      را از دست داده). فعال‌سازی را خودِ کاربر از صفحهٔ «امنیت حساب» انجام می‌دهد تا
      شمارهٔ موبایلش تأیید شود.
    </p>
  </div>
</template>
