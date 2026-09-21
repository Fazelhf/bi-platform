<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { crmApi, type CrmCustomer, type Deal } from "@/api/crm";
import { rial } from "@/utils/format";

/**
 * جستجوی سراسری — one box for the whole CRM.
 *
 * «Where is X» used to mean guessing which list X lived in, opening it, and
 * checking the date filter had not hidden it. This searches customers (by
 * name, contact, phone or code) and deals (all statuses, all time) at once,
 * scoped exactly as the lists are. Ctrl+K or «/» opens it from anywhere in
 * CRM; the arrow keys and Enter drive it without the mouse.
 */
const router = useRouter();

const open = ref(false);
const q = ref("");
const loading = ref(false);
const customers = ref<CrmCustomer[]>([]);
const deals = ref<Deal[]>([]);
const active = ref(0);
const input = ref<HTMLInputElement | null>(null);

type Hit = { kind: "customer" | "deal"; id: number };
const hits = computed<Hit[]>(() => [
  ...customers.value.map((c) => ({ kind: "customer" as const, id: c.id })),
  ...deals.value.map((d) => ({ kind: "deal" as const, id: d.id })),
]);

let timer: number | undefined;
let seq = 0;
watch(q, (v) => {
  window.clearTimeout(timer);
  active.value = 0;
  if (v.trim().length < 2) {
    customers.value = [];
    deals.value = [];
    return;
  }
  timer = window.setTimeout(async () => {
    const mine = ++seq;
    loading.value = true;
    try {
      const res = await crmApi.search(v.trim());
      // A slow answer to an older query must not overwrite a newer one.
      if (mine !== seq) return;
      customers.value = res.customers;
      deals.value = res.deals;
    } finally {
      if (mine === seq) loading.value = false;
    }
  }, 250);
});

async function show() {
  open.value = true;
  await nextTick();
  input.value?.focus();
  input.value?.select();
}
function hide() { open.value = false; }

function go(hit: Hit | undefined) {
  if (!hit) return;
  hide();
  router.push(hit.kind === "customer"
    ? { name: "crm-customer", params: { id: hit.id } }
    : { name: "crm-deal", params: { id: hit.id } });
}

function onKey(e: KeyboardEvent) {
  if (e.key === "ArrowDown") { e.preventDefault(); active.value = Math.min(active.value + 1, hits.value.length - 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); active.value = Math.max(active.value - 1, 0); }
  else if (e.key === "Enter") { e.preventDefault(); go(hits.value[active.value]); }
  else if (e.key === "Escape") hide();
}

/** Ctrl/⌘+K anywhere, or «/» when not already typing into something. */
function onGlobalKey(e: KeyboardEvent) {
  const typing = e.target instanceof HTMLElement && e.target.closest("input, textarea, select, [contenteditable]");
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); show(); }
  else if (e.key === "/" && !typing) { e.preventDefault(); show(); }
}
onMounted(() => window.addEventListener("keydown", onGlobalKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onGlobalKey));

const statusClass: Record<string, string> = {
  won: "bg-emerald-100 text-emerald-700",
  lost: "bg-red-100 text-red-600",
  open: "bg-amber-100 text-amber-700",
};
const idx = (kind: "customer" | "deal", i: number) => (kind === "customer" ? i : customers.value.length + i);
</script>

<template>
  <button
    class="hidden sm:flex items-center gap-2 text-sm text-slate-400 bg-slate-100 hover:bg-slate-200 rounded-xl px-3 py-1.5 w-56 transition"
    @click="show"
  >
    <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M20 20l-3.5-3.5" /></svg>
    <span class="flex-1 text-right">جستجو در CRM…</span>
    <kbd class="text-[10px] bg-surface rounded px-1.5 py-0.5 text-slate-400 ltr-nums" dir="ltr">Ctrl K</kbd>
  </button>
  <button class="sm:hidden text-slate-500 p-1" aria-label="جستجو" @click="show">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M20 20l-3.5-3.5" /></svg>
  </button>

  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] bg-black/40 backdrop-blur-[2px] flex items-start justify-center pt-[12vh] px-4" dir="rtl" @click.self="hide">
      <div class="w-full max-w-xl bg-surface rounded-2xl shadow-pop overflow-hidden">
        <div class="flex items-center gap-3 px-4 border-b border-slate-100">
          <svg class="w-5 h-5 text-slate-400 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7" /><path stroke-linecap="round" d="M20 20l-3.5-3.5" /></svg>
          <input
            ref="input" v-model="q"
            placeholder="نام مشتری، شماره تماس، کد یا عنوان معامله…"
            class="flex-1 bg-transparent py-4 text-ink outline-none text-sm"
            @keydown="onKey"
          />
          <span v-if="loading" class="w-4 h-4 border-2 border-slate-200 border-t-slate-500 rounded-full animate-spin"></span>
          <kbd class="text-[10px] bg-slate-100 rounded px-1.5 py-0.5 text-slate-400" dir="ltr">Esc</kbd>
        </div>

        <div class="max-h-[60vh] overflow-y-auto">
          <p v-if="q.trim().length < 2" class="px-4 py-8 text-center text-xs text-slate-400">
            دست‌کم دو حرف بنویسید · با ↑ ↓ جابه‌جا شوید و Enter را بزنید
          </p>
          <p v-else-if="!loading && !hits.length" class="px-4 py-8 text-center text-sm text-slate-400">
            چیزی پیدا نشد
          </p>

          <template v-if="customers.length">
            <p class="px-4 pt-3 pb-1 text-[11px] text-slate-400">مشتری‌ها</p>
            <button
              v-for="(c, i) in customers" :key="`c-${c.id}`"
              class="w-full text-right px-4 py-2.5 flex items-center gap-3"
              :class="active === idx('customer', i) ? 'bg-slate-100' : 'hover:bg-slate-50'"
              @mouseenter="active = idx('customer', i)"
              @click="go({ kind: 'customer', id: c.id })"
            >
              <span class="w-8 h-8 rounded-full bg-sky-100 text-sky-700 flex items-center justify-center text-xs font-bold shrink-0">{{ c.name_fa.slice(0, 1) }}</span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-ink truncate">{{ c.name_fa }}</span>
                <span class="block text-[11px] text-slate-400 truncate">
                  {{ [c.contact_name, c.mobile || c.phone, c.province_name, c.owner_name].filter(Boolean).join(" · ") }}
                </span>
              </span>
              <span class="text-[10px] text-slate-400 shrink-0">{{ c.status_display }}</span>
            </button>
          </template>

          <template v-if="deals.length">
            <p class="px-4 pt-3 pb-1 text-[11px] text-slate-400">معامله‌ها</p>
            <button
              v-for="(d, i) in deals" :key="`d-${d.id}`"
              class="w-full text-right px-4 py-2.5 flex items-center gap-3"
              :class="active === idx('deal', i) ? 'bg-slate-100' : 'hover:bg-slate-50'"
              @mouseenter="active = idx('deal', i)"
              @click="go({ kind: 'deal', id: d.id })"
            >
              <span class="w-8 h-8 rounded-lg bg-violet-100 text-violet-700 flex items-center justify-center shrink-0">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" d="M4 7h16v12H4zM9 7V5h6v2" /></svg>
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-sm text-ink truncate">{{ d.title }}</span>
                <span class="block text-[11px] text-slate-400 truncate">{{ d.customer_name }} · {{ d.stage_name }} · {{ d.opened_jalali }}</span>
              </span>
              <span class="text-xs text-ink ltr-nums shrink-0">{{ rial(d.amount_rial) }}</span>
              <span class="text-[10px] rounded-full px-1.5 py-0.5 shrink-0" :class="statusClass[d.status]">{{ d.status_display }}</span>
            </button>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
