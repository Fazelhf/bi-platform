<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { sales2Api, type GradePart, type Settings, type Warehouse } from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";

/** تنظیمات فروش ۲ — the letterhead printed on every document, the policies, the warehouses. */
const inp = "w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300";

const s = ref<Settings | null>(null);
const warehouses = ref<Warehouse[]>([]);
const error = ref("");
const newWh = ref({ code: "", name_fa: "", address: "" });
const GRADE_PARTS: Record<GradePart, string> = {
  profit: "سودآوری", collection: "وصول و اعتبار", volume: "حجم و تداوم",
  strategic: "ارزش استراتژیک", service: "هزینه خدمت", growth: "پتانسیل رشد",
};
const weightSum = computed(() =>
  Object.values(s.value?.grade_weights ?? {}).reduce((a, b) => a + (Number(b) || 0), 0));

async function load() {
  [s.value, warehouses.value] = await Promise.all([sales2Api.settings(), sales2Api.warehouses()]);
}
onMounted(load);

async function save() {
  error.value = "";
  try {
    s.value = await sales2Api.saveSettings(s.value!);
    toast.success("تنظیمات ذخیره شد.");
  } catch (e) {
    error.value = apiError(e);
  }
}

async function addWarehouse() {
  if (!newWh.value.code || !newWh.value.name_fa) { error.value = "کد و نام انبار لازم است."; return; }
  try {
    await sales2Api.saveWarehouse({ ...newWh.value, is_active: true });
    newWh.value = { code: "", name_fa: "", address: "" };
    warehouses.value = await sales2Api.warehouses();
  } catch (e) {
    error.value = apiError(e);
  }
}

async function toggleWarehouse(w: Warehouse) {
  await sales2Api.saveWarehouse({ ...w, is_active: !w.is_active }, w.id);
  warehouses.value = await sales2Api.warehouses();
}
</script>

<template>
  <div v-if="!s" class="space-y-3"><Skeleton class="h-64 rounded-card" /></div>
  <div v-else class="grid lg:grid-cols-3 gap-4">
    <div class="bg-surface rounded-card shadow-soft p-4 lg:col-span-2 space-y-3">
      <h2 class="text-sm font-bold text-ink">سربرگ اسناد (مشخصات فروشنده)</h2>
      <div class="grid sm:grid-cols-2 gap-3">
        <div class="sm:col-span-2"><label class="text-xs text-slate-500 mb-1 block">نام شرکت</label><input v-model="s.company_name" :class="inp" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">شناسه ملی</label><input v-model="s.national_id" :class="inp" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">کد اقتصادی</label><input v-model="s.economic_code" :class="inp" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">شماره ثبت</label><input v-model="s.registration_no" :class="inp" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">کد پستی</label><input v-model="s.postal_code" :class="inp" /></div>
        <div class="sm:col-span-2"><label class="text-xs text-slate-500 mb-1 block">نشانی</label><input v-model="s.address" :class="inp" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">تلفن</label><input v-model="s.phone" :class="inp" /></div>
      </div>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">متن پایین اسناد (شرایط تحویل، شماره حساب و …)</label>
        <textarea v-model="s.print_terms" :class="inp" rows="4" />
      </div>

      <h2 class="text-sm font-bold text-ink pt-2">سیاست‌ها</h2>
      <div class="grid sm:grid-cols-3 gap-3">
        <div><label class="text-xs text-slate-500 mb-1 block">٪ ارزش افزوده پیش‌فرض</label><input v-model="s.vat_pct" :class="inp" inputmode="decimal" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">اعتبار پیش‌فاکتور (روز)</label><input v-model.number="s.proforma_valid_days" :class="inp" inputmode="numeric" /></div>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">عبور از سقف اعتبار</label>
          <select v-model="s.credit_policy" :class="inp">
            <option value="block">جلوگیری (با دلیل مجاز)</option>
            <option value="warn">فقط هشدار</option>
            <option value="off">بدون کنترل</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-slate-500 mb-1 block">انبار پیش‌فرض</label>
          <select v-model="s.default_warehouse" :class="inp">
            <option :value="null">—</option>
            <option v-for="w in warehouses.filter((x) => x.is_active)" :key="w.id" :value="w.id">{{ w.name_fa }}</option>
          </select>
        </div>
      </div>
      <h2 class="text-sm font-bold text-ink pt-2">کارت تصمیم پیش از صدور</h2>
      <div class="grid sm:grid-cols-3 gap-3">
        <div><label class="text-xs text-slate-500 mb-1 block">کف حاشیه‌ی سود مصوب (٪)</label><input v-model="s.margin_floor_pct" :class="inp" inputmode="decimal" /></div>
        <div><label class="text-xs text-slate-500 mb-1 block">سفارش بزرگ: چند برابر میانگین مشتری</label><input v-model="s.big_order_factor" :class="inp" inputmode="decimal" /></div>
      </div>
      <p class="text-xs text-slate-400">زیر کف حاشیه، سفارش بزرگ‌تر از الگوی مشتری و فروش اعتباری به گرید C فقط با نوشتن دلیل صادر می‌شود.</p>

      <h2 class="text-sm font-bold text-ink pt-2">وزن امتیاز گرید مشتری (٪)</h2>
      <div v-if="s.grade_weights" class="grid grid-cols-2 sm:grid-cols-6 gap-3">
        <div v-for="(label, k) in GRADE_PARTS" :key="k">
          <label class="text-xs text-slate-500 mb-1 block">{{ label }}</label>
          <input v-model.number="s.grade_weights[k]" :class="inp" inputmode="numeric" />
        </div>
      </div>
      <p class="text-xs" :class="weightSum === 100 ? 'text-slate-400' : 'text-amber-600'">
        جمع وزن‌ها: {{ weightSum }}٪ — وزن‌ها را مدیریت فروش و مالی تصویب می‌کنند.
      </p>
      <p v-if="error" class="text-sm text-red-600">{{ error }}</p>
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="save">ذخیره تنظیمات</button>
    </div>

    <div class="bg-surface rounded-card shadow-soft p-4 space-y-3">
      <h2 class="text-sm font-bold text-ink">انبارها</h2>
      <ul class="divide-y divide-slate-100 text-sm">
        <li v-for="w in warehouses" :key="w.id" class="py-2 flex items-center justify-between gap-2">
          <span :class="w.is_active ? 'text-ink' : 'text-slate-400 line-through'">{{ w.name_fa }} <span class="text-xs text-slate-400 ltr-nums">{{ w.code }}</span></span>
          <button class="text-xs text-slate-400 hover:text-ink" @click="toggleWarehouse(w)">{{ w.is_active ? "غیرفعال" : "فعال" }}</button>
        </li>
        <li v-if="!warehouses.length" class="py-2 text-slate-400 text-xs">هنوز انباری تعریف نشده.</li>
      </ul>
      <div class="space-y-2 pt-2 border-t border-slate-100">
        <input v-model="newWh.code" :class="inp" placeholder="کد (مثلاً WH1)" />
        <input v-model="newWh.name_fa" :class="inp" placeholder="نام انبار" />
        <input v-model="newWh.address" :class="inp" placeholder="نشانی (اختیاری)" />
        <button class="bg-slate-100 text-slate-700 rounded-xl px-4 py-2 text-sm w-full" @click="addWarehouse">+ افزودن انبار</button>
      </div>
    </div>
  </div>
</template>
