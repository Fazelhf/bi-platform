<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type DataCheck, type DataCheckRow } from "@/api/crm";
import { num } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import NavIcon from "@/components/NavIcon.vue";

/**
 * کنترل داده — what is wrong in CRM right now, and the records behind it.
 *
 * Checks are ordered by how much they distort a report: a deal on the wrong
 * customer moves money between accounts, a deal without an amount only
 * understates a forecast. Nothing here changes data; each row opens the
 * record so a person can fix it where it lives.
 */
const router = useRouter();
const checks = ref<DataCheck[]>([]);
const at = ref("");
const loading = ref(true);
const open = ref<string | null>(null);
const showClean = ref(false);

async function load() {
  loading.value = true;
  try {
    const r = await crmApi.checks();
    checks.value = r.checks;
    at.value = r.at;
    open.value = r.checks.find((c) => c.count && c.severity === "high")?.key ?? null;
  } finally {
    loading.value = false;
  }
}
onMounted(load);

const SEV = {
  high: { label: "جدی", dot: "bg-red-500", chip: "bg-red-50 text-red-600" },
  medium: { label: "مهم", dot: "bg-amber-500", chip: "bg-amber-50 text-amber-700" },
  low: { label: "تکمیلی", dot: "bg-slate-400", chip: "bg-slate-100 text-slate-500" },
} as const;

const visible = computed(() => checks.value.filter((c) => c.count || showClean.value));
const clean = computed(() => checks.value.filter((c) => !c.count).length);
const issues = computed(() => checks.value.filter((c) => c.count && c.severity === "high").length);

function openRow(r: DataCheckRow) {
  if (r.kind === "deal") router.push({ name: "crm-deal", params: { id: r.id } });
  else if (r.kind === "suspect") router.push({ name: "crm-settings", query: { section: "arpa", tab: "suspect" } });
  else if (r.customer_id) router.push({ name: "crm-customer", params: { id: r.customer_id } });
}

const card = "bg-surface rounded-card shadow-soft min-w-0";
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-3 px-1">
      <p class="text-sm text-ink font-semibold">
        <template v-if="!loading">
          {{ issues ? `${num(issues)} بررسی جدی مشکل دارد` : "مشکل جدی‌ای پیدا نشد" }}
        </template>
      </p>
      <span class="text-xs text-slate-400">{{ num(clean) }} بررسی بدون مشکل</span>
      <span class="flex-1"></span>
      <label class="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer">
        <input v-model="showClean" type="checkbox" /> نمایش بررسی‌های بدون مشکل
      </label>
      <button class="text-xs bg-surface shadow-soft rounded-xl px-3 py-1.5 text-slate-600 hover:text-ink" :disabled="loading" @click="load">
        بررسی دوباره
      </button>
    </div>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-14 rounded-card" /></div>

    <div v-for="c in visible" v-else :key="c.key" :class="card">
      <button class="w-full flex items-center gap-3 px-4 py-3 text-right" @click="open = open === c.key ? null : c.key">
        <span class="w-2 h-2 rounded-full shrink-0" :class="c.count ? SEV[c.severity].dot : 'bg-emerald-500'"></span>
        <span class="flex-1 min-w-0">
          <span class="block text-sm text-ink">{{ c.label }}</span>
          <span class="block text-[11px] text-slate-400 truncate">{{ c.why }}</span>
        </span>
        <span v-if="c.count" class="text-[11px] rounded-full px-2 py-0.5" :class="SEV[c.severity].chip">{{ SEV[c.severity].label }}</span>
        <span class="text-sm font-bold w-14 text-left" :class="c.count ? 'text-ink' : 'text-emerald-600'">{{ c.count ? num(c.count) : "✓" }}</span>
        <NavIcon name="chevron" :size="16" class="text-slate-400 transition" :class="open === c.key ? 'rotate-90' : '-rotate-90'" />
      </button>
      <div v-if="open === c.key && c.rows.length" class="border-t border-slate-100 overflow-x-auto">
        <table class="w-full text-xs min-w-[520px]">
          <tbody>
            <tr
              v-for="r in c.rows" :key="`${r.kind}-${r.id}-${r.detail}`"
              class="border-b border-slate-50 hover:bg-slate-50 cursor-pointer"
              @click="openRow(r)"
            >
              <td class="px-4 py-2 text-ink">{{ r.title }}</td>
              <td class="py-2 text-slate-500 truncate max-w-[220px]">{{ r.customer }}</td>
              <td class="py-2 pl-4 text-slate-400 text-left whitespace-nowrap">{{ r.detail }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="c.count > c.rows.length" class="text-[11px] text-slate-400 px-4 py-2">
          {{ num(c.rows.length) }} مورد اول از {{ num(c.count) }}
        </p>
      </div>
    </div>
  </div>
</template>
