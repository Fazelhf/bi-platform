<script setup lang="ts">
import { computed } from "vue";
import { useCrmStore } from "@/stores/crm";

/** The one filter bar every CRM page shares (state lives in the store). */
const crm = useCrmStore();
const emit = defineEmits<{ (e: "change"): void }>();

const months = computed(() => crm.options?.months ?? []);
const employees = computed(() => crm.options?.employees ?? []);
const groups = computed(() => crm.options?.groups ?? []);
const sources = computed(() => crm.options?.sources ?? []);
const provinces = computed(() => crm.options?.provinces ?? []);

function changed() { emit("change"); }

const active = computed(() =>
  [crm.filters.owner, crm.filters.group, crm.filters.source, crm.filters.province]
    .filter((v) => v !== "").length,
);

const sel = "bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none border-0 focus:ring-2 focus:ring-slate-300 min-w-0";
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2 no-print">
    <select v-model="crm.filters.range" :class="sel" @change="changed">
      <option value="current">ماه جاری</option>
      <option value="last3">۳ ماه اخیر</option>
      <option value="last6">۶ ماه اخیر</option>
      <option value="last12">۱۲ ماه اخیر</option>
      <option value="month">یک ماه مشخص</option>
      <option value="custom">بازه دلخواه</option>
    </select>

    <select v-if="crm.filters.range === 'month'" v-model="crm.filters.month" :class="sel" @change="changed">
      <option v-for="m in months" :key="m.key" :value="m.key">{{ m.label }}</option>
    </select>

    <template v-if="crm.filters.range === 'custom'">
      <input v-model="crm.filters.date_from" type="date" :class="sel" @change="changed" />
      <span class="text-slate-400 text-xs">تا</span>
      <input v-model="crm.filters.date_to" type="date" :class="sel" @change="changed" />
    </template>

    <span class="w-px h-6 bg-slate-200 mx-1 hidden sm:block"></span>

    <select v-model="crm.filters.owner" :class="sel" @change="changed">
      <option value="">همه کارشناسان</option>
      <option v-for="e in employees" :key="e.id" :value="e.id">{{ e.name }}</option>
    </select>

    <select v-model="crm.filters.group" :class="sel" @change="changed">
      <option value="">همه گروه‌ها</option>
      <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name_fa }}</option>
    </select>

    <select v-model="crm.filters.source" :class="sel" @change="changed">
      <option value="">همه شیوه‌های آشنایی</option>
      <option v-for="s in sources" :key="s.id" :value="s.id">{{ s.name_fa }}</option>
    </select>

    <select v-model="crm.filters.province" :class="sel" @change="changed">
      <option value="">همه استان‌ها</option>
      <option v-for="p in provinces" :key="p.id" :value="p.id">{{ p.name_fa }}</option>
    </select>

    <button
      v-if="active"
      class="text-xs text-red-500 hover:bg-red-50 rounded-xl px-3 py-2"
      @click="crm.reset(); changed()"
    >حذف {{ active }} فیلتر</button>

    <span class="flex-1"></span>
    <span class="text-xs text-slate-400 px-2">{{ crm.rangeLabel }}</span>
  </div>
</template>
