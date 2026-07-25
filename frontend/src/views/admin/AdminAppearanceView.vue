<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useUiStore } from "@/stores/ui";
import { PALETTES } from "@/components/charts/palettes";
import SeriesChart from "@/components/charts/SeriesChart.vue";

const ui = useUiStore();
const saving = ref("");

async function pick(key: string) {
  saving.value = "در حال ذخیره…";
  try {
    await ui.setTheme(key);
    saving.value = "طرح گرافیکی روی همه‌ی چارت‌های سایت اعمال شد ✓";
  } catch {
    saving.value = "خطا در ذخیره";
  }
  window.setTimeout(() => (saving.value = ""), 4000);
}

// Sample data so each theme can be previewed live.
const cats = ["برش ۱", "برش ۲", "برش ۳", "برش ۴"];
const demo = [
  { name: "واقعی", values: [372049, 399843, 373550, 120000] },
  { name: "مطلوب", values: [416000, 416000, 432000, 480000] },
];

onMounted(() => ui.fetch());
</script>

<template>
  <div class="space-y-4">
    <div>
      <h2 class="text-lg font-bold text-ink">طرح گرافیکی چارت‌ها</h2>
      <p class="text-xs text-slate-400 mt-0.5">
        یکی از چهار طرح را انتخاب کنید. انتخاب شما روی <b>همه‌ی چارت‌های همه‌ی بخش‌ها</b>
        (فروش، تولید، نمای کلی) به‌صورت هماهنگ اعمال می‌شود.
      </p>
    </div>

    <p v-if="saving" class="text-sm bg-accent-50 text-accent-700 rounded-xl p-2">{{ saving }}</p>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div
        v-for="p in PALETTES"
        :key="p.key"
        class="rounded-card border-2 transition cursor-pointer bg-surface p-3"
        :class="ui.chartTheme === p.key ? 'border-accent-500 shadow-pop' : 'border-transparent shadow-soft hover:border-slate-200'"
        @click="pick(p.key)"
      >
        <div class="flex items-center justify-between mb-2 px-1">
          <span class="font-semibold text-ink text-sm">{{ p.label }}</span>
          <span v-if="ui.chartTheme === p.key" class="text-xs bg-accent-500 text-white rounded-full px-2 py-0.5">فعال</span>
        </div>
        <!-- Swatches -->
        <div class="flex gap-1 px-1 mb-2">
          <span v-for="c in p.series.slice(0, 6)" :key="c" class="w-6 h-6 rounded-lg" :style="{ background: c }"></span>
        </div>
        <!-- Live preview (renders with the *active* theme once selected) -->
        <SeriesChart title="پیش‌نمایش" :categories="cats" :series="demo" :height="170" />
      </div>
    </div>
  </div>
</template>
