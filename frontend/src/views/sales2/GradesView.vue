<script setup lang="ts">
/**
 * گرید مشتریان — کتاب فروش، فصل ۱۷. The system scores every customer who
 * bought in the last year and suggests A/B/C; management approves the grade
 * (SP only by hand). The salesperson does not change it.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { sales2Api, type Grade, type GradePart, type GradeRow } from "@/api/sales2";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";
import { apiError } from "@/components/crm/formError";
import { toast } from "@/composables/useUi";

const router = useRouter();
const FA = new Intl.NumberFormat("fa-IR");
const rows = ref<GradeRow[]>([]);
const parts = ref<Record<GradePart, string>>({} as Record<GradePart, string>);
const weights = ref<Record<GradePart, number>>({} as Record<GradePart, number>);
const loading = ref(true);
const error = ref("");
const q = ref("");
const filter = ref<"" | "pending" | "differs" | Grade>("");
const open = ref<number | null>(null);
const draft = ref<{ grade: Grade | ""; strategic: number; note: string }>({ grade: "", strategic: 50, note: "" });

async function load() {
  loading.value = true;
  try {
    const d = await sales2Api.grades(q.value.trim());
    rows.value = d.rows; parts.value = d.parts; weights.value = d.weights;
  } catch (e) { error.value = apiError(e); }
  finally { loading.value = false; }
}
let timer: ReturnType<typeof setTimeout> | undefined;
watch(q, () => { clearTimeout(timer); timer = setTimeout(load, 300); });
onMounted(load);

const shown = computed(() => rows.value.filter((r) =>
  !filter.value ? true
    : filter.value === "pending" ? !r.grade
      : filter.value === "differs" ? !!r.grade && r.grade !== "SP" && r.grade !== r.suggested
        : r.grade === filter.value));
const counts = computed(() => {
  const c: Record<string, number> = { SP: 0, A: 0, B: 0, C: 0, pending: 0 };
  for (const r of rows.value) c[r.grade || "pending"]++;
  return c;
});

function edit(r: GradeRow) {
  open.value = open.value === r.customer ? null : r.customer;
  draft.value = { grade: r.grade || r.suggested, strategic: r.strategic_score, note: r.grade_note };
}
async function save(r: GradeRow) {
  try {
    const res = await sales2Api.setGrade(r.customer, {
      grade: draft.value.grade, strategic_score: draft.value.strategic, note: draft.value.note,
    });
    toast.success(`گرید ${r.name}: ${res.grade || "—"}`);
    open.value = null;
    await load();
  } catch (e) { error.value = apiError(e); }
}

const GRADE_CLS: Record<string, string> = {
  SP: "bg-violet-100 text-violet-700", A: "bg-emerald-100 text-emerald-700",
  B: "bg-sky-100 text-sky-700", C: "bg-red-100 text-red-700",
};
const bar = (v: number) => (v >= 75 ? "bg-emerald-500" : v >= 50 ? "bg-sky-500" : v >= 25 ? "bg-amber-500" : "bg-red-500");
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input v-model="q" placeholder="نام یا کد مشتری…" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none flex-1 min-w-[180px]" />
      <div class="flex flex-wrap gap-1 text-xs">
        <button class="rounded-full px-3 py-1" :class="!filter ? 'bg-panel text-white' : 'bg-slate-100 text-slate-600'" @click="filter = ''">همه {{ FA.format(rows.length) }}</button>
        <button class="rounded-full px-3 py-1" :class="filter === 'pending' ? 'bg-panel text-white' : 'bg-amber-50 text-amber-700'" @click="filter = 'pending'">تأییدنشده {{ FA.format(counts.pending) }}</button>
        <button v-for="g in ['SP', 'A', 'B', 'C']" :key="g" class="rounded-full px-3 py-1" :class="filter === g ? 'bg-panel text-white' : GRADE_CLS[g]" @click="filter = g as Grade">{{ g }} {{ FA.format(counts[g]) }}</button>
        <button class="rounded-full px-3 py-1" :class="filter === 'differs' ? 'bg-panel text-white' : 'bg-slate-100 text-slate-600'" @click="filter = 'differs'">مغایر با پیشنهاد</button>
      </div>
    </div>

    <p class="text-xs text-slate-500 px-1">
      امتیاز از فروش ۱۲ ماه اخیر:
      <template v-for="(label, k, i) in parts" :key="k">{{ i ? " · " : "" }}{{ label }} {{ FA.format(weights[k]) }}٪</template>.
      ۷۵+ پیشنهاد A، ۵۰+ پیشنهاد B، کمتر C؛ SP فقط با تصمیم مدیریت. گرید را مدیریت تأیید می‌کند، نه فروشنده.
    </p>
    <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2">{{ error }}</p>

    <div v-if="loading" class="space-y-2"><Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" /></div>
    <EmptyState v-else-if="!shown.length" title="مشتری‌ای نیست" hint="مشتریانی که در ۱۲ ماه اخیر فاکتور صادرشده دارند اینجا می‌آیند." />
    <div v-else class="bg-surface rounded-card shadow-soft overflow-x-auto">
      <table class="w-full text-sm min-w-[900px]">
        <thead>
          <tr class="text-xs text-slate-400 bg-slate-50">
            <th class="text-right font-medium px-4 py-3">مشتری</th>
            <th class="text-right font-medium px-2">امتیاز</th>
            <th v-for="(label, k) in parts" :key="k" class="text-right font-medium px-2 whitespace-nowrap">{{ label }}</th>
            <th class="text-right font-medium px-2">پیشنهاد</th>
            <th class="text-right font-medium px-2">گرید تأییدشده</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <template v-for="r in shown" :key="r.customer">
            <tr class="border-t border-slate-100 hover:bg-slate-50">
              <td class="px-4 py-2 min-w-[200px]">
                <button class="text-ink font-medium hover:underline text-right" @click="router.push({ name: 'sales2-customer', params: { id: r.customer } })">{{ r.name }}</button>
                <p class="text-xs text-slate-400">{{ r.owner_name || "—" }}</p>
              </td>
              <td class="px-2 font-bold text-ink ltr-nums">{{ FA.format(r.score) }}</td>
              <td v-for="(_, k) in parts" :key="k" class="px-2" :title="r.facts[k]">
                <div class="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden"><div class="h-full" :class="bar(r.parts[k])" :style="{ width: `${r.parts[k]}%` }" /></div>
                <span class="text-[10px] text-slate-400 block truncate max-w-[90px]">{{ r.facts[k] }}</span>
              </td>
              <td class="px-2"><span class="rounded-full px-2 py-0.5 text-xs" :class="GRADE_CLS[r.suggested]">{{ r.suggested }}</span></td>
              <td class="px-2">
                <span v-if="r.grade" class="rounded-full px-2 py-0.5 text-xs font-bold" :class="GRADE_CLS[r.grade]">{{ r.grade }}</span>
                <span v-else class="text-xs text-amber-600">تأیید نشده</span>
                <span v-if="r.grade_set_by" class="text-[10px] text-slate-400 block">{{ r.grade_set_by }}</span>
              </td>
              <td class="px-3 text-left"><button class="text-xs rounded-lg px-2 py-1 bg-slate-100 text-slate-700" @click="edit(r)">{{ r.grade ? "تغییر" : "تأیید" }}</button></td>
            </tr>
            <tr v-if="open === r.customer" class="bg-slate-50">
              <td :colspan="5 + Object.keys(parts).length" class="px-4 py-3">
                <div class="flex flex-wrap items-end gap-3">
                  <div>
                    <label class="text-xs text-slate-500 block mb-1">گرید</label>
                    <div class="flex gap-1">
                      <button v-for="g in ['SP', 'A', 'B', 'C'] as Grade[]" :key="g" class="rounded-lg px-3 py-1.5 text-sm" :class="draft.grade === g ? GRADE_CLS[g] + ' ring-2 ring-slate-400' : 'bg-white text-slate-500'" @click="draft.grade = g">{{ g }}</button>
                    </div>
                  </div>
                  <div>
                    <label class="text-xs text-slate-500 block mb-1">ارزش استراتژیک (۰ تا ۱۰۰)</label>
                    <input v-model.number="draft.strategic" type="number" min="0" max="100" class="bg-white rounded-xl px-3 py-1.5 text-sm w-28 outline-none" />
                  </div>
                  <div class="flex-1 min-w-[200px]">
                    <label class="text-xs text-slate-500 block mb-1">دلیل / یادداشت</label>
                    <input v-model="draft.note" class="bg-white rounded-xl px-3 py-1.5 text-sm w-full outline-none" placeholder="مثلاً قرارداد سالانه، نفوذ در بازار، چک برگشتی…" />
                  </div>
                  <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="save(r)">ثبت گرید</button>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>
