<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  crmApi,
  type MatchCandidate,
  type MatchSide,
  type MatchSummary,
} from "@/api/crm";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * بازبینی تطبیق — the queue the matcher refused to decide.
 *
 * The importer merges only what it is certain of, because a wrong merge fuses
 * two companies' order histories and nothing on any screen looks wrong
 * afterwards. What is left is 160 pairs that need a person: a shared
 * switchboard, a name one word apart, a name the CRM already holds twice.
 *
 * The screen is built as a comparison rather than a list. Every field is laid
 * out on the same row on both sides so the eye can run down the middle, and
 * the fields that actually settle it — a national id, a postcode, a phone —
 * are highlighted when they agree and when they differ. Two names side by
 * side is not enough information to decide, and a reviewer given only that
 * will start clicking «same» to clear the queue.
 *
 * «رد» is not «discard». It means these are different customers, so the
 * accounting party becomes an account of its own — otherwise its invoices
 * stay unimportable, and 543bn Rial of them are waiting on this queue.
 */
const rows = ref<MatchCandidate[]>([]);
const summary = ref<MatchSummary | null>(null);
const loading = ref(true);
const busy = ref<number | null>(null);
const error = ref("");
const method = ref("");
const state = ref<"pending" | "accepted" | "rejected" | "all">("pending");
const search = ref("");
const alternatives = ref<Record<number, MatchSide[]>>({});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, sum] = await Promise.all([
      crmApi.matchCandidates({
        state: state.value,
        method: method.value,
        search: search.value,
        page_size: 50,
      }),
      crmApi.matchSummary(),
    ]);
    rows.value = list.results;
    summary.value = sum;
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "خطا در خواندن صف بازبینی.";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch([method, state], load);
let t: number | undefined;
watch(search, () => {
  window.clearTimeout(t);
  t = window.setTimeout(load, 350);
});

/** Drop the settled card out of the list rather than reloading the queue —
 *  a reviewer working down 160 rows must not lose their place on every click. */
function settle(id: number) {
  rows.value = rows.value.filter((r) => r.id !== id);
  if (summary.value) summary.value.pending = Math.max(summary.value.pending - 1, 0);
}

async function accept(row: MatchCandidate, customer?: number) {
  busy.value = row.id;
  error.value = "";
  try {
    await crmApi.acceptMatch(row.id, customer);
    settle(row.id);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "ادغام انجام نشد.";
  } finally {
    busy.value = null;
  }
}

async function reject(row: MatchCandidate) {
  busy.value = row.id;
  error.value = "";
  try {
    await crmApi.rejectMatch(row.id);
    settle(row.id);
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? "ثبت نشد.";
  } finally {
    busy.value = null;
  }
}

async function showAlternatives(row: MatchCandidate) {
  if (alternatives.value[row.id]) {
    delete alternatives.value[row.id];
    return;
  }
  alternatives.value[row.id] = await crmApi.matchAlternatives(row.id);
}

/** The rows of the comparison, in the order that settles a decision fastest:
 *  identifiers first, then contact details, then the descriptive fields. */
const FIELDS: { key: keyof MatchSide; label: string; strong?: boolean }[] = [
  { key: "national_id", label: "شناسه / کد ملی", strong: true },
  { key: "economic_code", label: "کد اقتصادی", strong: true },
  { key: "phone", label: "تلفن", strong: true },
  { key: "mobile", label: "موبایل", strong: true },
  { key: "city", label: "شهر" },
  { key: "province", label: "استان" },
  { key: "address", label: "آدرس" },
];

/** Last eight significant digits — «02144641330» and «44641330» are one number. */
function digits(v: unknown): string {
  const d = String(v ?? "").replace(/\D/g, "").replace(/^0+/, "");
  return d.length >= 8 ? d.slice(-8) : "";
}

/**
 * Whether a field agrees across the two systems.
 *
 * Compared as a *group* rather than field to field, because the systems do
 * not agree on which box a number belongs in: the switchboard that produced a
 * phone match is often آرپا's «تلفن» against the CRM's «موبایل», and a
 * national id is routinely typed into the economic-code column. Compared
 * strictly, the very evidence behind the match renders red — which tells the
 * reviewer the opposite of the truth.
 */
const PHONE_KEYS: (keyof MatchSide)[] = ["phone", "mobile"];
const ID_KEYS: (keyof MatchSide)[] = ["national_id", "economic_code"];

function agrees(row: MatchCandidate, key: keyof MatchSide): "same" | "differ" | "" {
  const group = PHONE_KEYS.includes(key)
    ? PHONE_KEYS
    : ID_KEYS.includes(key)
      ? ID_KEYS
      : null;

  if (!group) {
    const a = String(row.crm[key] ?? "").trim();
    const b = String(row.arpa[key] ?? "").trim();
    if (!a || !b) return "";
    return a === b ? "same" : "differ";
  }

  const norm = PHONE_KEYS.includes(key) ? digits : (v: unknown) => String(v ?? "").trim();
  const mine = norm(row.crm[key]);
  if (!mine) return "";
  const theirs = group.map((k) => norm(row.arpa[k])).filter(Boolean);
  if (!theirs.length) return "";
  return theirs.includes(mine) ? "same" : "differ";
}

const methodTone: Record<string, string> = {
  ambig: "bg-violet-100 text-violet-700",
  branch: "bg-amber-100 text-amber-700",
  phone: "bg-sky-100 text-sky-700",
  fuzzy: "bg-orange-100 text-orange-700",
  nid: "bg-emerald-100 text-emerald-700",
};

const hint: Record<string, string> = {
  ambig:
    "نام دقیقاً یکسان است ولی چند مشتری در CRM همین نام را دارند — یعنی خود CRM تکراری دارد. اول انتخاب کن کدام حساب واقعی است.",
  branch:
    "شناسه ملی یکی است ولی نام دو شهر متفاوت را می‌گوید. شعب یک بانک شناسه ملی مشترک دارند؛ شعبه‌ی متفاوت مشتری متفاوت است.",
  phone:
    "فقط تلفن یکی است. یک شماره‌ی سانترال بین چند سازمان مشترک می‌شود؛ به شهر و آدرس هم نگاه کن.",
  fuzzy: "نام‌ها شبیه‌اند ولی یکسان نیستند.",
  nid: "شناسه ملی یکی است.",
};

const total = computed(() => summary.value?.pending ?? 0);
</script>

<template>
  <div class="space-y-4">
    <header class="flex flex-wrap items-center gap-3">
      <div class="flex-1">
        <h1 class="text-lg font-bold">بازبینی تطبیق مشتریان</h1>
        <p class="mt-1 text-sm text-slate-500">
          مواردی که تطبیق خودکار به آن‌ها اطمینان نکرد. تا وقتی تعیین تکلیف
          نشوند، فاکتورهایشان هم وارد نمی‌شود.
        </p>
      </div>
      <span
        v-if="total"
        class="rounded-full bg-amber-100 px-3 py-1 text-sm font-bold text-amber-700"
      >{{ total }} مورد باز</span>
    </header>

    <div class="flex flex-wrap items-center gap-2">
      <button
        class="rounded-lg px-3 py-1.5 text-sm"
        :class="method === '' ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600'"
        @click="method = ''"
      >همه</button>
      <button
        v-for="m in summary?.by_method ?? []"
        :key="m.key"
        class="rounded-lg px-3 py-1.5 text-sm"
        :class="method === m.key ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-600'"
        @click="method = m.key"
      >{{ m.label }} ({{ m.count }})</button>

      <select v-model="state" class="rounded-lg border border-slate-200 px-2 py-1.5 text-sm">
        <option value="pending">در انتظار</option>
        <option value="accepted">تاییدشده</option>
        <option value="rejected">ردشده</option>
        <option value="all">همه</option>
      </select>
      <input
        v-model="search"
        placeholder="جستجوی نام…"
        class="w-48 rounded-lg border border-slate-200 px-3 py-1.5 text-sm"
      />
    </div>

    <p v-if="error" class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
      {{ error }}
    </p>

    <Skeleton v-if="loading" class="h-64" />
    <EmptyState
      v-else-if="!rows.length"
      title="چیزی برای بازبینی نیست"
      subtitle="همه‌ی موارد تعیین تکلیف شده‌اند."
    />

    <article
      v-for="row in rows"
      v-else
      :key="row.id"
      class="rounded-xl border border-slate-200 bg-white p-4"
    >
      <div class="mb-3 flex flex-wrap items-center gap-2">
        <span
          class="rounded-full px-2 py-0.5 text-xs font-bold"
          :class="methodTone[row.method] ?? 'bg-slate-100 text-slate-600'"
        >{{ row.method_display }}</span>
        <span class="text-xs text-slate-400">کد آرپا: {{ row.external_id }}</span>
        <span v-if="row.state !== 'pending'" class="text-xs text-slate-500">
          — {{ row.state_display }}
          <template v-if="row.decided_by_name">توسط {{ row.decided_by_name }}</template>
        </span>
      </div>

      <p class="mb-3 text-xs text-slate-500">{{ hint[row.method] }}</p>

      <div class="grid gap-3 sm:grid-cols-2">
        <section class="rounded-lg bg-slate-50 p-3">
          <p class="mb-1 text-xs text-slate-400">مشتری فعلی CRM</p>
          <p class="font-bold">{{ row.crm.name_fa }}</p>
          <p class="mt-1 text-xs text-slate-500">
            {{ row.crm.code }}
            <template v-if="row.crm.owner"> · {{ row.crm.owner }}</template>
          </p>
          <p class="mt-1 text-xs text-slate-500">
            {{ row.crm.deals }} معامله · {{ row.crm.invoices }} فاکتور
          </p>
        </section>
        <section class="rounded-lg bg-sky-50 p-3">
          <p class="mb-1 text-xs text-slate-400">طرف‌حساب حسابداری</p>
          <p class="font-bold">{{ row.arpa.name_fa }}</p>
          <p class="mt-1 text-xs text-slate-500">
            {{ row.arpa.group }}
            <template v-if="row.arpa.rep"> · {{ row.arpa.rep }}</template>
          </p>
          <p v-if="row.arpa.terms" class="mt-1 text-xs text-slate-500">
            شرایط تسویه: {{ row.arpa.terms }}
          </p>
        </section>
      </div>

      <table class="mt-3 w-full text-sm">
        <tbody>
          <tr
            v-for="f in FIELDS"
            :key="String(f.key)"
            class="border-t border-slate-100"
          >
            <td class="w-32 py-1.5 text-xs text-slate-400">{{ f.label }}</td>
            <td
              class="py-1.5"
              :class="{
                'bg-emerald-50 font-bold': f.strong && agrees(row, f.key) === 'same',
                'bg-red-50': f.strong && agrees(row, f.key) === 'differ',
              }"
            >{{ row.crm[f.key] || "—" }}</td>
            <td
              class="py-1.5"
              :class="{
                'bg-emerald-50 font-bold': f.strong && agrees(row, f.key) === 'same',
                'bg-red-50': f.strong && agrees(row, f.key) === 'differ',
              }"
            >{{ row.arpa[f.key] || "—" }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="alternatives[row.id]" class="mt-3 space-y-1">
        <p class="text-xs text-slate-400">مشتریان دیگری با همین نام:</p>
        <button
          v-for="alt in alternatives[row.id]"
          :key="alt.id"
          class="flex w-full items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-right text-sm hover:bg-emerald-50"
          :disabled="busy === row.id"
          @click="accept(row, alt.id)"
        >
          <span class="flex-1">{{ alt.name_fa }}</span>
          <span class="text-xs text-slate-400">
            {{ alt.deals }} معامله · {{ alt.invoices }} فاکتور
          </span>
          <span class="text-xs text-emerald-600">این یکی</span>
        </button>
      </div>

      <div v-if="row.state === 'pending'" class="mt-3 flex flex-wrap gap-2">
        <button
          class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-50"
          :disabled="busy === row.id"
          @click="accept(row)"
        >همان مشتری است</button>
        <button
          class="rounded-lg bg-slate-100 px-4 py-2 text-sm font-bold text-slate-700 disabled:opacity-50"
          :disabled="busy === row.id"
          @click="reject(row)"
        >مشتری دیگری است — حساب تازه بساز</button>
        <button
          v-if="row.method === 'ambig'"
          class="rounded-lg px-3 py-2 text-sm text-sky-600"
          @click="showAlternatives(row)"
        >{{ alternatives[row.id] ? "بستن" : "مشتریان هم‌نام" }}</button>
      </div>
    </article>
  </div>
</template>
