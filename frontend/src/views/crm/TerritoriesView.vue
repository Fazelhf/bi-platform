<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type TerritoryRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { toast } from "@/composables/useUi";
import Skeleton from "@/components/Skeleton.vue";

/**
 * مناطق و مسئولان — each province's sales manager and کارشناس(ان), per sales
 * book. Tehran opens into its sales zones. Only people on the sales roster
 * can be picked; the server checks it again.
 *
 * This decides what the map and reports show as «مسئول»; it does not change
 * what anyone may see — that stays with the account's own access.
 */
const crm = useCrmStore();
const rows = ref<TerritoryRow[]>([]);
const loading = ref(true);
const busy = ref(false);
const search = ref("");

const CHANNELS = [
  { key: "team", label: "فروش همکار" },
  { key: "organizational", label: "بانکی" },
  { key: "b2b", label: "B2B" },
  { key: "psp", label: "PSP" },
];
/** A department account works in its own book; the CEO picks one. */
const channel = ref<string>("team");
const canManage = computed(() => crm.canEdit && crm.isManager);

async function load() {
  loading.value = true;
  try {
    rows.value = await crmApi.territories();
  } finally {
    loading.value = false;
  }
}
onMounted(async () => { await crm.loadOptions(); await load(); });

const provinces = computed(() =>
  (crm.options?.provinces ?? []).filter((p) => !search.value || p.name_fa.includes(search.value)),
);

function inSlot(province: number, zone: number | null, role: "manager" | "expert") {
  // A department account only ever receives its own book's rows.
  return rows.value.filter((r) => (!crm.seesAll || r.channel === channel.value) && r.province === province
    && (r.zone ?? null) === zone && r.role === role);
}

async function add(province: number, zone: number | null, role: "manager" | "expert", employee: number | "") {
  if (!employee) return;
  busy.value = true;
  try {
    await crmApi.saveTerritory({
      province, zone, role, employee: Number(employee),
      // The server stamps a department account's own book.
      ...(crm.seesAll ? { channel: channel.value } : {}),
    });
    await load();
  } catch (e: any) {
    const d = e?.response?.data;
    toast.error(d?.detail ?? (d ? String(Object.values(d)[0]) : "ثبت نشد."));
  } finally {
    busy.value = false;
  }
}

async function remove(r: TerritoryRow) {
  busy.value = true;
  try {
    await crmApi.deleteTerritory(r.id);
    await load();
  } finally {
    busy.value = false;
  }
}

const unassigned = computed(() =>
  (crm.options?.provinces ?? []).filter((p) => !inSlot(p.id, null, "manager").length && !inSlot(p.id, null, "expert").length).length,
);
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 space-y-4">
    <header class="flex flex-wrap items-center gap-2">
      <div class="flex-1 min-w-[240px]">
        <h2 class="text-lg font-bold">مناطق و مسئولان</h2>
        <p class="text-sm text-slate-500 mt-1">
          مدیر فروش و کارشناسان هر استان. استانی که مسئول ندارد روی نقشه «مسئول تعیین نشده» نشان داده می‌شود
          و فروشش به نام کارشناسِ هر فاکتور ثبت می‌ماند. {{ unassigned }} استان بدون مسئول.
        </p>
      </div>
      <select v-if="crm.seesAll" v-model="channel" class="bg-slate-100 rounded-xl px-3 py-2 text-sm" aria-label="دفتر فروش">
        <option v-for="c in CHANNELS" :key="c.key" :value="c.key">{{ c.label }}</option>
      </select>
      <input v-model="search" placeholder="جستجوی استان…" aria-label="جستجوی استان"
             class="bg-slate-100 rounded-xl px-3 py-2 text-sm w-44 outline-none" />
    </header>
    <p v-if="!canManage" class="text-xs text-slate-400">تعیین مسئول با مدیر فروش است؛ این‌جا فقط نمایش است.</p>

    <Skeleton v-if="loading" class="h-64" />
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-xs text-slate-400 bg-slate-50">
          <th class="text-right font-medium px-3 py-2 w-40">استان / محدوده</th>
          <th class="text-right font-medium px-3 w-56">مدیر فروش</th>
          <th class="text-right font-medium px-3">کارشناسان</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="p in provinces" :key="p.id">
          <tr v-for="slot in [{ zone: null, label: p.name_fa }, ...(!crm.seesAll || channel === 'team' ? crm.zonesOf(p.id).map((z) => ({ zone: z.id, label: '— ' + z.name_fa })) : [])]"
              :key="`${p.id}-${slot.zone}`" class="border-t border-slate-100 align-top">
            <td class="px-3 py-2" :class="slot.zone ? 'text-slate-500 pr-6' : 'text-ink font-medium'">{{ slot.label }}</td>
            <td class="px-3 py-2">
              <span v-for="r in inSlot(p.id, slot.zone, 'manager')" :key="r.id"
                    class="inline-flex items-center gap-1 bg-sky-50 text-sky-800 rounded-full px-2 py-0.5 text-xs">
                {{ r.employee_name }}
                <button v-if="canManage" class="text-sky-400 hover:text-red-500" :disabled="busy"
                        :aria-label="`حذف ${r.employee_name}`" @click="remove(r)">×</button>
              </span>
              <select v-if="canManage" class="bg-transparent text-xs text-slate-500 mt-1 block outline-none"
                      :disabled="busy" aria-label="مدیر فروش"
                      @change="add(p.id, slot.zone, 'manager', Number(($event.target as HTMLSelectElement).value)); ($event.target as HTMLSelectElement).value = ''">
                <option value="">{{ inSlot(p.id, slot.zone, 'manager').length ? "تغییر مدیر…" : "+ مدیر" }}</option>
                <option v-for="e in crm.rosterEmployees" :key="e.id" :value="e.id">{{ e.name }}</option>
              </select>
            </td>
            <td class="px-3 py-2">
              <div class="flex flex-wrap gap-1">
                <span v-for="r in inSlot(p.id, slot.zone, 'expert')" :key="r.id"
                      class="inline-flex items-center gap-1 bg-slate-100 text-slate-700 rounded-full px-2 py-0.5 text-xs">
                  {{ r.employee_name }}
                  <button v-if="canManage" class="text-slate-400 hover:text-red-500" :disabled="busy"
                          :aria-label="`حذف ${r.employee_name}`" @click="remove(r)">×</button>
                </span>
                <select v-if="canManage" class="bg-transparent text-xs text-slate-500 outline-none" :disabled="busy"
                        aria-label="افزودن کارشناس"
                        @change="add(p.id, slot.zone, 'expert', Number(($event.target as HTMLSelectElement).value)); ($event.target as HTMLSelectElement).value = ''">
                  <option value="">+ کارشناس</option>
                  <option v-for="e in crm.rosterEmployees.filter((x) => !inSlot(p.id, slot.zone, 'expert').some((r) => r.employee === x.id))"
                          :key="e.id" :value="e.id">{{ e.name }}</option>
                </select>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
