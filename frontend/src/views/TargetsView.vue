<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import api from "@/api/client";
import { salesApi } from "@/api/sales";
import { defaultPeriodId } from "@/types";
import type { Period } from "@/types";
import MoneyInput from "@/components/MoneyInput.vue";
import DashboardSkeleton from "@/components/DashboardSkeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import ExportActions from "@/components/ExportActions.vue";
import { toast } from "@/composables/useUi";
import { num } from "@/utils/format";

/**
 * The CEO's targets desk. Department managers record actuals on their entry
 * sheets but cannot touch targets — those are set here, per channel, for
 * each salesperson and each province.
 */
interface PersonRow {
  employee_id: number;
  name: string;
  team: string;
  is_active: boolean;
  target_rial: string;
  revenue_rial: string;
}
interface ProvinceRow { province_id: number; name: string; target_rial: string; sales_rial: string }

const CHANNELS = [
  { key: "team", label: "فروش همکار" },
  { key: "organizational", label: "فروش بانکی" },
  { key: "b2b", label: "فروش B2B" },
];

const periods = ref<Period[]>([]);
const selectedPeriod = ref<number | null>(null);
const channel = ref("team");
const people = ref<PersonRow[]>([]);
const provinces = ref<ProvinceRow[]>([]);
const loading = ref(true);
const saving = ref(false);
const provinceSearch = ref("");

const visibleProvinces = computed(() => {
  const q = provinceSearch.value.trim();
  return q ? provinces.value.filter((p) => p.name.includes(q)) : provinces.value;
});

const peopleTotal = computed(() =>
  people.value.reduce((s, p) => s + Number(p.target_rial || 0), 0),
);
const provinceTotal = computed(() =>
  provinces.value.reduce((s, p) => s + Number(p.target_rial || 0), 0),
);

async function load() {
  if (!selectedPeriod.value) return;
  loading.value = true;
  try {
    const { data } = await api.get("/sales/targets/", {
      params: { period: selectedPeriod.value, channel: channel.value },
    });
    people.value = data.people;
    provinces.value = data.provinces;
  } finally {
    loading.value = false;
  }
}

async function save(quiet = false) {
  saving.value = true;
  try {
    await api.post("/sales/targets/", {
      period: selectedPeriod.value,
      channel: channel.value,
      people: people.value,
      provinces: provinces.value,
    });
    if (quiet) {
      autoSaved.value = true;
      window.setTimeout(() => (autoSaved.value = false), 2500);
    } else {
      toast.success("تارگت‌ها ذخیره شد و شاخص‌ها دوباره محاسبه شدند.");
    }
  } catch {
    toast.error("ذخیره نشد.");
  } finally {
    saving.value = false;
  }
}

/**
 * Auto-save while the CEO types.
 *
 * Targets are a short list typed in one sitting, and losing them to a closed
 * tab is pure waste — so the sheet saves itself a moment after the typing
 * stops. Debounced rather than saved per keystroke because every save also
 * recomputes the period's KPIs; the explicit button stays for anyone who
 * wants the confirmation.
 */
const autoSaved = ref(false);
let autoTimer: number | undefined;
let loaded = false;

watch([people, provinces], () => {
  // Skip the change that loading the sheet itself causes.
  if (!loaded || loading.value) return;
  window.clearTimeout(autoTimer);
  autoTimer = window.setTimeout(() => save(true), 1500);
}, { deep: true });

onMounted(async () => {
  periods.value = await salesApi.periods();
  selectedPeriod.value = defaultPeriodId(periods.value);
  await load();
  loaded = true;
});
watch([selectedPeriod, channel], async () => {
  // A pending auto-save belongs to the sheet being left, not the new one.
  window.clearTimeout(autoTimer);
  loaded = false;
  await load();
  loaded = true;
});
</script>

<template>
  <div class="space-y-4 pb-8">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">تعیین تارگت</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          تارگت‌ها را شما تعیین می‌کنید؛ مدیران بخش‌ها آن‌ها را می‌بینند ولی نمی‌توانند تغییر دهند.
          همهٔ کارشناسان اینجا فهرست شده‌اند — حتی پیش از آنکه مدیر فروش آن‌ها را به برگهٔ ورود اضافه کند.
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <ExportActions :excel="false" />
        <select
          v-model.number="selectedPeriod"
          class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30 transition"
        >
          <option v-for="p in periods" :key="p.id" :value="p.id">{{ p.label }}</option>
        </select>
      </div>
    </div>

    <!-- Channel tabs -->
    <div class="flex gap-1 flex-wrap no-print">
      <button
        v-for="c in CHANNELS"
        :key="c.key"
        class="px-4 py-1.5 rounded-xl text-sm transition-colors"
        :class="channel === c.key ? 'bg-panel text-white' : 'bg-surface border border-slate-200 hover:bg-slate-50'"
        @click="channel = c.key"
      >{{ c.label }}</button>
    </div>

    <DashboardSkeleton v-if="loading" :cards="0" :charts="0" :rows="8" />

    <template v-else>
      <!-- Per salesperson -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-ink">تارگت فروشندگان</h3>
          <span class="text-sm text-slate-400">
            جمع: <span class="ltr-nums font-semibold text-ink">{{ num(peopleTotal) }}</span> ریال
          </span>
        </div>
        <div v-if="people.length" class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <div
            v-for="p in people"
            :key="p.employee_id"
            class="grid grid-cols-[1fr_auto] items-center gap-3"
          >
            <div class="min-w-0">
              <p class="text-sm text-ink truncate">
                {{ p.name }}
                <span v-if="p.team" class="text-[11px] text-slate-400">· {{ p.team }}</span>
                <span v-if="!p.is_active" class="text-[11px] text-amber-600">· غیرفعال</span>
              </p>
              <p class="text-[11px] text-slate-400 ltr-nums">
                فروش این ماه: {{ num(Number(p.revenue_rial || 0)) }}
              </p>
            </div>
            <MoneyInput
              v-model="p.target_rial"
              placeholder="تارگت"
              class="w-36 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-left ltr-nums outline-none transition"
            />
          </div>
        </div>
        <EmptyState
          v-else
          icon="🎯"
          title="فروشنده‌ای در این کانال نیست"
          hint="پس از اینکه مدیر بخش فروشندگان این ماه را ثبت کند، اینجا برای تعیین تارگت ظاهر می‌شوند."
        />
      </section>

      <!-- Per province -->
      <section class="bg-surface rounded-card shadow-soft p-5">
        <div class="flex items-center justify-between gap-3 mb-1 flex-wrap">
          <h3 class="font-bold text-ink">تارگت استان‌ها</h3>
          <div class="flex items-center gap-3">
            <span class="text-sm text-slate-400">
              جمع: <span class="ltr-nums font-semibold text-ink">{{ num(provinceTotal) }}</span> ریال
            </span>
            <input
              v-model="provinceSearch"
              placeholder="جستجوی استان…"
              class="bg-slate-50 border border-slate-200 rounded-xl px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-accent-500/30 transition"
            />
          </div>
        </div>
        <p class="text-xs text-slate-400 mb-4">
          استان‌هایی که تارگت ندارند را صفر بگذارید.
        </p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
          <div
            v-for="p in visibleProvinces"
            :key="p.province_id"
            class="grid grid-cols-[1fr_auto] items-center gap-3"
          >
            <div class="min-w-0">
              <p class="text-sm text-slate-600 truncate">{{ p.name }}</p>
              <p class="text-[11px] text-slate-400 ltr-nums">
                فروش: {{ num(Number(p.sales_rial || 0)) }}
              </p>
            </div>
            <MoneyInput
              v-model="p.target_rial"
              placeholder="تارگت"
              class="w-36 bg-slate-50 focus:bg-surface border border-transparent focus:border-accent-500 rounded-lg px-2 py-1.5 text-left ltr-nums outline-none transition"
            />
          </div>
        </div>
        <p v-if="!visibleProvinces.length" class="text-sm text-slate-400 py-3">استانی با این نام پیدا نشد.</p>
      </section>

      <!-- z-30: the table's frozen first/last columns are z-10/z-20, so without
           this the sheet scrolled over the save buttons. -->
      <div class="sticky bottom-4 z-30 bg-panel text-white rounded-card shadow-pop p-3 flex items-center justify-between">
        <span v-if="autoSaved" class="text-xs text-accent-300 px-2">✓ ذخیره خودکار</span>
        <span class="text-sm text-white/70 px-2">
          با ذخیره، درصد تحقق تارگت در همه‌ی داشبوردها دوباره محاسبه می‌شود.
        </span>
        <button
          class="px-5 py-2 rounded-xl bg-accent-500 hover:bg-accent-600 text-sm font-medium disabled:opacity-50 transition-colors"
          :disabled="saving"
          @click="save(false)"
        >{{ saving ? "در حال ذخیره…" : "ذخیره تارگت‌ها" }}</button>
      </div>
    </template>
  </div>
</template>
