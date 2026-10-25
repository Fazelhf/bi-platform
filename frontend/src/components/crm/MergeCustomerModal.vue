<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type CrmCustomer, type SimilarCustomer } from "@/api/crm";
import { num } from "@/utils/format";
import FormModal from "./FormModal.vue";
import CustomerPicker from "./CustomerPicker.vue";

/**
 * «ادغام با مشتری دیگر» — two rows that are one customer, joined from the
 * customer page itself.
 *
 * Suggestions come first (same id, same phone, a name sharing its words) and
 * any customer can be searched. Before anything happens the screen says which
 * one stays and what moves, because a merge fuses two order histories and is
 * not visible afterwards. The absorbed customer is kept and marked, not
 * deleted, and the pair is recorded in بازبینی تطبیق.
 */
const props = defineProps<{ customer: CrmCustomer }>();
const emit = defineEmits<{ (e: "close"): void; (e: "merged", id: number): void }>();

const similar = ref<SimilarCustomer[]>([]);
const loading = ref(true);
const otherId = ref<number | "">("");
const otherLabel = ref("");
const keep = ref<"this" | "other">("this");
const saving = ref(false);
const error = ref("");

onMounted(async () => {
  try {
    similar.value = await crmApi.similarCustomers(props.customer.id);
  } finally {
    loading.value = false;
  }
});

function onPicked(v: number | "") {
  otherId.value = v;
}
function onLabel(v: string) {
  otherLabel.value = v;
}

function pick(s: SimilarCustomer) {
  otherId.value = s.id;
  otherLabel.value = s.name_fa;
}

const picked = computed(() => similar.value.find((s) => s.id === otherId.value) ?? null);
const survivorName = computed(() => (keep.value === "this" ? props.customer.name_fa : otherLabel.value));
const absorbedName = computed(() => (keep.value === "this" ? otherLabel.value : props.customer.name_fa));

async function save() {
  if (!otherId.value) {
    error.value = "مشتری دوم را انتخاب کنید.";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const res = await crmApi.mergeCustomer(props.customer.id, Number(otherId.value), keep.value);
    emit("merged", res.id);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "ادغام انجام نشد.";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <FormModal
    title="ادغام با مشتری دیگر"
    :subtitle="customer.name_fa"
    :saving="saving"
    :error="error"
    wide
    save-label="ادغام"
    @close="emit('close')"
    @save="save"
  >
    <div class="space-y-4 text-sm">
      <div>
        <p class="text-xs text-slate-500 mb-2">مشتری‌های شبیه</p>
        <p v-if="loading" class="text-xs text-slate-400">در حال پیدا کردن…</p>
        <p v-else-if="!similar.length" class="text-xs text-slate-400">مشتری شبیهی پیدا نشد؛ از جستجو استفاده کنید.</p>
        <ul v-else class="space-y-1.5 max-h-56 overflow-y-auto">
          <li v-for="s in similar" :key="s.id">
            <button
              type="button"
              class="w-full text-right rounded-xl border px-3 py-2 transition"
              :class="otherId === s.id ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:bg-slate-50'"
              @click="pick(s)"
            >
              <span class="flex items-center justify-between gap-2">
                <span class="text-ink font-medium">{{ s.name_fa }}</span>
                <span class="text-[11px] text-slate-400 whitespace-nowrap">{{ num(s.deals) }} معامله · {{ num(s.invoices) }} فاکتور</span>
              </span>
              <span class="block text-[11px] text-slate-500 mt-0.5">
                {{ [s.province, s.city, s.owner, s.phone, s.national_id].filter(Boolean).join(" · ") || "—" }}
              </span>
              <span class="flex flex-wrap gap-1 mt-1">
                <span v-for="w in s.why" :key="w" class="text-[10px] bg-amber-50 text-amber-700 rounded-full px-2 py-0.5">{{ w }}</span>
              </span>
            </button>
          </li>
        </ul>
      </div>

      <div>
        <p class="text-xs text-slate-500 mb-1">یا جستجو</p>
        <CustomerPicker
          :model-value="otherId"
          :label="otherLabel"
          placeholder="نام، موبایل یا کد مشتری دوم…"
          @update:model-value="onPicked"
          @update:label="onLabel"
        />
      </div>

      <div v-if="otherId" class="rounded-xl bg-slate-50 p-3 space-y-2">
        <p class="text-xs text-slate-500">کدام بماند؟</p>
        <label class="flex items-center gap-2 cursor-pointer">
          <input v-model="keep" type="radio" value="this" /> <span class="text-ink">{{ customer.name_fa }}</span>
          <span class="text-[11px] text-slate-400">(همین مشتری)</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input v-model="keep" type="radio" value="other" /> <span class="text-ink">{{ otherLabel }}</span>
        </label>
        <p class="text-xs text-slate-600 leading-6 pt-1 border-t border-slate-200">
          همه‌ی معامله‌ها، فاکتورها، فعالیت‌ها، کارها و کدهای آرپا/دیدارِ
          <b>«{{ absorbedName }}»</b> به <b>«{{ survivorName }}»</b> منتقل می‌شود
          و جاهای خالی «{{ survivorName }}» از آن پر می‌شود.
          «{{ absorbedName }}» پاک نمی‌شود؛ «ادغام‌شده» علامت می‌خورد و در بازبینی تطبیق ثبت می‌شود.
          <template v-if="picked"> ({{ num(picked.deals) }} معامله و {{ num(picked.invoices) }} فاکتورِ مشتری دوم)</template>
        </p>
      </div>
    </div>
  </FormModal>
</template>
