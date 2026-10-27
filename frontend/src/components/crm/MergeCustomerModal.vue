<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { crmApi, MOVED_LABELS, type CrmCustomer, type SimilarCustomer } from "@/api/crm";
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
/** The second customer in full, for the side-by-side table. */
const other = ref<(CrmCustomer & Record<string, any>) | null>(null);
/** Set once the merge is done: what moved, shown before the modal closes. */
const result = ref<{ id: number; moved: Record<string, number> } | null>(null);

watch(otherId, async (id) => {
  other.value = null;
  if (id) other.value = await crmApi.customer(Number(id)).catch(() => null);
});

/** The fields a reviewer compares, and which side's value survives: the
 *  survivor's, unless it is blank — exactly what the backend does. */
const COMPARE: [string, string][] = [
  ["phone", "تلفن"], ["mobile", "موبایل"], ["national_id", "شناسه/کد ملی"],
  ["province_name", "استان"], ["city", "شهر"], ["address", "آدرس"],
  ["owner_name", "کارشناس"], ["group_name", "گروه"], ["contact_name", "رابط"],
  ["status_display", "وضعیت"],
];
const COUNTS: [string, string][] = [
  ["deals", "معامله"], ["activities", "فعالیت"], ["open_tasks", "کار باز"],
];
const me = computed(() => props.customer as CrmCustomer & Record<string, any>);
const sides = computed(() =>
  keep.value === "this" ? { keepRow: me.value, goneRow: other.value } : { keepRow: other.value, goneRow: me.value },
);
/** Column `i` (0 = this customer, 1 = the other) holds the value that stays. */
function wins(field: string, i: number): boolean {
  const survivorCol = keep.value === "this" ? 0 : 1;
  if (sides.value.keepRow?.[field]) return i === survivorCol;
  return !!sides.value.goneRow?.[field] && i !== survivorCol;
}

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
  if (result.value) {
    emit("merged", result.value.id);
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    const res = await crmApi.mergeCustomer(props.customer.id, Number(otherId.value), keep.value);
    result.value = { id: res.id, moved: res.moved ?? {} };
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
    :save-label="result ? 'بستن و رفتن به مشتری' : 'ادغام'"
    @close="emit('close')"
    @save="save"
  >
    <div v-if="result" class="space-y-3 text-sm">
      <p class="rounded-xl bg-emerald-50 p-3 text-emerald-800">
        «{{ absorbedName }}» در «{{ survivorName }}» ادغام شد. سابقه‌ی ادغام در صفحه‌ی مشتری ثبت است.
      </p>
      <ul class="grid grid-cols-2 gap-2">
        <li v-for="(n, k) in result.moved" :key="k" class="rounded-lg bg-slate-50 px-3 py-2 flex justify-between">
          <span class="text-slate-500">{{ MOVED_LABELS[k] ?? k }}</span><b class="ltr-nums">{{ num(n) }}</b>
        </li>
        <li v-if="!Object.keys(result.moved).length" class="text-slate-400">چیزی برای انتقال نبود.</li>
      </ul>
    </div>
    <div v-else class="space-y-4 text-sm">
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
        <table v-if="other" class="w-full text-xs border-t border-slate-200">
          <thead>
            <tr class="text-slate-400">
              <th class="text-right font-normal py-1 w-24"></th>
              <th class="text-right font-normal py-1">{{ customer.name_fa }}</th>
              <th class="text-right font-normal py-1">{{ other.name_fa }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[f, label] in COMPARE" :key="f" class="border-t border-slate-100">
              <td class="py-1 text-slate-400">{{ label }}</td>
              <td v-for="(row, i) in [me, other]" :key="i" class="py-1"
                  :class="wins(f, i) ? 'bg-emerald-50 font-semibold text-ink' : 'text-slate-500'">
                {{ row?.[f] || "—" }}
              </td>
            </tr>
            <tr v-for="[f, label] in COUNTS" :key="f" class="border-t border-slate-100">
              <td class="py-1 text-slate-400">{{ label }}</td>
              <td class="py-1 ltr-nums">{{ num(me.stats?.[f] ?? 0) }}</td>
              <td class="py-1 ltr-nums">{{ num(other.stats?.[f] ?? 0) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="other" class="text-[11px] text-slate-400">سبز: مقداری که بعد از ادغام می‌ماند. شمارنده‌ها جمع می‌شوند.</p>
        <p class="text-xs text-slate-600 leading-6 pt-1 border-t border-slate-200">
          همه‌ی معامله‌ها، فاکتورها، فعالیت‌ها، کارها، برچسب‌ها، اسناد مالی و کدهای آرپا/دیدارِ
          <b>«{{ absorbedName }}»</b> به <b>«{{ survivorName }}»</b> منتقل می‌شود
          و جاهای خالی «{{ survivorName }}» از آن پر می‌شود؛ «آخرین فعالیت» دوباره از روی فعالیت‌ها حساب می‌شود.
          «{{ absorbedName }}» پاک نمی‌شود؛ «ادغام‌شده» علامت می‌خورد و در بازبینی تطبیق ثبت می‌شود.
          <template v-if="picked"> ({{ num(picked.deals) }} معامله و {{ num(picked.invoices) }} فاکتورِ مشتری دوم)</template>
        </p>
      </div>
    </div>
  </FormModal>
</template>
