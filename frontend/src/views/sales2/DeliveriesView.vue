<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { sales2Api, type Delivery, type Options } from "@/api/sales2";
import DeliveryForm from "@/components/sales2/DeliveryForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { confirm, prompt, toast } from "@/composables/useUi";
import { faDate } from "@/utils/adminFormat";

/** حواله‌های خروج — what left the warehouse, against which invoice, on whose truck. */
const route = useRoute();
const FA = new Intl.NumberFormat("fa-IR");

const rows = ref<Delivery[]>([]);
const options = ref<Options | null>(null);
const loading = ref(true);
const error = ref("");
const search = ref("");
const status = ref("");
const formOpen = ref(false);
const editing = ref<Delivery | null>(null);
const forInvoice = ref<number | null>(null);

const STATUS_CLASS: Record<string, string> = {
  draft: "bg-slate-100 text-slate-600",
  issued: "bg-emerald-100 text-emerald-700",
  cancelled: "bg-red-100 text-red-600",
};

async function load() {
  loading.value = true;
  try {
    rows.value = await sales2Api.deliveries({ search: search.value.trim(), status: status.value });
  } catch (e) {
    error.value = apiError(e);
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;
watch(search, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
watch(status, load);
onMounted(async () => {
  options.value = await sales2Api.options();
  if (route.query.invoice) {
    forInvoice.value = Number(route.query.invoice);
    formOpen.value = true;
  }
  await load();
});

function openForm(d: Delivery | null) {
  editing.value = d;
  forInvoice.value = d ? d.invoice : null;
  formOpen.value = true;
}

function onSaved() {
  formOpen.value = false;
  toast.success("حواله ثبت شد.");
  load();
}

async function issue(d: Delivery) {
  try {
    await sales2Api.issueDelivery(d.id);
  } catch (e: any) {
    const data = e?.response?.data;
    if (!data?.needs_reason) { error.value = apiError(e); return; }
    const reason = await prompt({
      title: "صدور حواله با عبور از کنترل",
      message: (data.checks ?? []).map((c: { message: string }) => `• ${c.message}`).join("\n") + "\n\nدلیل صدور را بنویسید.",
    });
    if (!reason?.trim()) return;
    try { await sales2Api.issueDelivery(d.id, reason.trim()); } catch (e2) { error.value = apiError(e2); return; }
  }
  load();
}
async function cancel(d: Delivery) {
  const reason = await prompt({ title: `ابطال حواله ${d.number}`, message: "دلیل ابطال؟" });
  if (!reason?.trim()) return;
  try { await sales2Api.cancelDelivery(d.id, reason.trim()); load(); } catch (e) { error.value = apiError(e); }
}
async function remove(d: Delivery) {
  if (!(await confirm({ title: "حذف پیش‌نویس حواله", message: "حذف شود؟", danger: true }))) return;
  await sales2Api.removeDelivery(d.id);
  load();
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="شماره حواله، فاکتور، مشتری، راننده یا بارنامه…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[200px]"
      />
      <select v-model="status" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه وضعیت‌ها</option>
        <option value="draft">پیش‌نویس</option>
        <option value="issued">خارج شده</option>
        <option value="cancelled">ابطال</option>
      </select>
      <span class="text-xs text-slate-400 px-2">{{ FA.format(rows.length) }} حواله</span>
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="openForm(null)">+ حواله خروج</button>
    </div>

    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <DeliveryForm
      v-if="formOpen && options" :options="options" :invoice-id="forInvoice" :delivery="editing"
      @close="formOpen = false" @saved="onSaved"
    />

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState v-else-if="!rows.length" title="حواله‌ای ثبت نشده" hint="حواله از روی فاکتور صادرشده زده می‌شود." />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[900px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">شماره</th>
            <th class="text-right font-medium px-3">تاریخ</th>
            <th class="text-right font-medium px-3">فاکتور / مشتری</th>
            <th class="text-right font-medium px-3">اقلام</th>
            <th class="text-right font-medium px-3">حمل</th>
            <th class="text-right font-medium px-3">وضعیت</th>
            <th class="px-3"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in rows" :key="d.id" class="border-t border-slate-100 align-top">
            <td class="px-4 py-2.5 ltr-nums text-ink font-medium">{{ d.number || `پیش‌نویس #${d.id}` }}</td>
            <td class="px-3 text-xs text-slate-500">{{ faDate(d.delivery_date) }}</td>
            <td class="px-3">
              <router-link
                :to="{ name: 'sales2-document', params: { id: d.invoice }, query: { kind: 'invoice' } }"
                class="ltr-nums text-sky-600"
              >{{ d.invoice_number }}</router-link>
              <p class="text-xs text-slate-500">{{ d.customer_name }}</p>
            </td>
            <td class="px-3 text-xs text-slate-600">
              <p v-for="l in d.lines" :key="l.id">{{ l.product_name }} × <span class="ltr-nums">{{ FA.format(Number(l.quantity)) }}</span> {{ l.unit }}</p>
            </td>
            <td class="px-3 text-xs text-slate-500">
              <p v-if="d.driver_name">{{ d.driver_name }} <span class="ltr-nums">{{ d.vehicle_plate }}</span></p>
              <p v-if="d.waybill_no">بارنامه <span class="ltr-nums">{{ d.waybill_no }}</span></p>
              <p v-if="d.receiver_name">تحویل: {{ d.receiver_name }}</p>
            </td>
            <td class="px-3">
              <span class="text-xs rounded-full px-2 py-0.5" :class="STATUS_CLASS[d.status]">{{ d.status_label }}</span>
              <p v-if="d.cancel_reason" class="text-xs text-red-500">{{ d.cancel_reason }}</p>
            </td>
            <td class="px-3 text-left whitespace-nowrap">
              <template v-if="d.status === 'draft'">
                <button class="text-xs text-sky-600 px-1" @click="issue(d)">صدور</button>
                <button class="text-xs text-slate-400 px-1" @click="openForm(d)">ویرایش</button>
                <button class="text-xs text-slate-400 hover:text-red-500 px-1" @click="remove(d)">حذف</button>
              </template>
              <button v-else-if="d.status === 'issued'" class="text-xs text-slate-400 hover:text-red-500 px-1" @click="cancel(d)">ابطال</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
