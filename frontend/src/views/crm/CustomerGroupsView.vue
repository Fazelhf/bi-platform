<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { crmApi, type CustomerGroupRow } from "@/api/crm";
import { useCrmStore } from "@/stores/crm";
import { useRouter } from "vue-router";
import { num } from "@/utils/format";
import { toast } from "@/composables/useUi";
import Skeleton from "@/components/Skeleton.vue";

/**
 * گروه‌های مشتری — create, rename, move every customer of one group to
 * another, delete. Deleting asks where the group's customers go first: a
 * group removed with customers in it would leave them silently ungrouped.
 * A system group can be renamed but not deleted.
 */
const crm = useCrmStore();
const router = useRouter();
const groups = ref<CustomerGroupRow[]>([]);
const loading = ref(true);
const busy = ref(false);
const newName = ref("");
const editing = ref<number | null>(null);
const editName = ref("");
/** The group a move or delete is being set up for, and where its customers go. */
const acting = ref<{ group: CustomerGroupRow; mode: "move" | "delete" } | null>(null);
const target = ref<number | "">("");

const canManage = computed(() => crm.canEdit && crm.isManager);

/** The sales books a group can belong to (the CEO picks; blank = shared). */
const BOOKS = [
  { value: "team", label: "فروش همکار" },
  { value: "organizational", label: "فروش بانکی" },
  { value: "b2b", label: "فروش B2B" },
  { value: "psp", label: "فروش PSP" },
];

async function setOwner(g: CustomerGroupRow, channel: string) {
  try {
    await crmApi.saveGroup({ channel } as any, g.id);
    await refreshAll();
  } catch (e) {
    fail(e, "دفتر مالک ذخیره نشد.");
  }
}

/** The customer list, filtered to this group — the same customers it counts. */
function showCustomers(g: CustomerGroupRow) {
  crm.filters.group = g.id;
  router.push({ name: "crm-customers" });
}

async function load() {
  loading.value = true;
  try {
    groups.value = await crmApi.groups();
  } finally {
    loading.value = false;
  }
}
onMounted(async () => { await crm.loadOptions(); await load(); });

function fail(e: any, fallback: string) {
  const d = e?.response?.data;
  toast.error(d?.detail ?? d?.move_to?.[0] ?? d?.name_fa?.[0] ?? fallback);
}

/** The filter bar and the customer forms read groups from `/options/`. */
async function refreshAll() {
  await load();
  crm.options = null as any;
  await crm.loadOptions();
  crm.bump();
}

async function create() {
  if (!newName.value.trim()) return;
  busy.value = true;
  try {
    await crmApi.saveGroup({ name_fa: newName.value.trim() });
    newName.value = "";
    await refreshAll();
  } catch (e) {
    fail(e, "گروه ساخته نشد.");
  } finally {
    busy.value = false;
  }
}

async function rename(g: CustomerGroupRow) {
  const name = editName.value.trim();
  editing.value = null;
  if (!name || name === g.name_fa) return;
  try {
    await crmApi.saveGroup({ name_fa: name }, g.id);
    await refreshAll();
  } catch (e) {
    fail(e, "نام ذخیره نشد.");
  }
}

function open(group: CustomerGroupRow, mode: "move" | "delete") {
  acting.value = { group, mode };
  target.value = "";
}

async function confirmAct() {
  if (!acting.value) return;
  const { group, mode } = acting.value;
  if ((mode === "move" || group.customer_count) && !target.value) {
    toast.error("گروه مقصد را انتخاب کنید.");
    return;
  }
  busy.value = true;
  try {
    if (mode === "move") {
      const r = await crmApi.moveGroup(group.id, Number(target.value));
      toast.success(`${num(r.moved)} مشتری منتقل شد`);
    } else {
      const r = await crmApi.deleteGroup(group.id, target.value ? Number(target.value) : undefined);
      toast.success(`گروه حذف شد${r.moved ? ` و ${num(r.moved)} مشتری منتقل شد` : ""}`);
    }
    acting.value = null;
    await refreshAll();
  } catch (e) {
    fail(e, "انجام نشد.");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="bg-surface rounded-card shadow-soft p-4 space-y-4">
    <header>
      <h2 class="text-lg font-bold">گروه‌های مشتری</h2>
      <p class="text-sm text-slate-500 mt-1">
        برای جابه‌جایی چند مشتری خاص، در فهرست مشتریان تیکشان بزنید و «ویرایش گروهی ← گروه» را بزنید.
      </p>
    </header>

    <form v-if="canManage" class="flex gap-2" @submit.prevent="create">
      <input v-model="newName" placeholder="نام گروه تازه…" aria-label="نام گروه تازه"
             class="flex-1 bg-slate-100 rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-slate-300" />
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm disabled:opacity-50" :disabled="busy || !newName.trim()">
        + گروه جدید
      </button>
    </form>
    <p v-else class="text-xs text-slate-400">ساختن، تغییر و حذف گروه با مدیر فروش است.</p>

    <Skeleton v-if="loading" class="h-40" />
    <table v-else class="w-full text-sm">
      <thead>
        <tr class="text-xs text-slate-400 bg-slate-50">
          <th class="text-right font-medium px-3 py-2">نام</th>
          <th class="text-right font-medium px-3">مشتری</th>
          <th class="text-right font-medium px-3">دفتر مالک</th>
          <th class="text-right font-medium px-3">مشتری‌ها در هر دفتر</th>
          <th class="px-3"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="g in groups" :key="g.id" class="border-t border-slate-100">
          <td class="px-3 py-2">
            <input v-if="editing === g.id" v-model="editName" class="bg-white border border-sky-300 rounded-lg px-2 py-1 text-sm"
                   aria-label="نام گروه" @keydown.enter.prevent="rename(g)" @keydown.esc="editing = null" @blur="rename(g)" />
            <template v-else>
              <button class="text-ink hover:text-sky-600 hover:underline" title="دیدن مشتری‌های این گروه" @click="showCustomers(g)">{{ g.name_fa }}</button>
              <span v-if="g.is_system" class="mr-2 text-[10px] bg-slate-100 text-slate-500 rounded-full px-2 py-0.5"
                    title="گروه سیستمی: نامش عوض می‌شود ولی حذف نمی‌شود">سیستمی</span>
            </template>
          </td>
          <td class="px-3 ltr-nums text-slate-500">{{ num(g.customer_count) }}</td>
          <td class="px-3">
            <select v-if="crm.seesAll && canManage" :value="g.channel" class="bg-slate-100 rounded-lg px-2 py-1 text-xs"
                    aria-label="دفتر مالک" @change="setOwner(g, ($event.target as HTMLSelectElement).value)">
              <option value="">مشترک</option>
              <option v-for="b in BOOKS" :key="b.value" :value="b.value">{{ b.label }}</option>
            </select>
            <span v-else class="text-xs" :class="g.channel ? 'text-ink' : 'text-slate-400'">{{ g.channel_display || "مشترک" }}</span>
          </td>
          <td class="px-3 text-[11px] text-slate-500">
            <span v-for="b in g.by_book" :key="b.channel" class="ml-2 whitespace-nowrap">{{ b.label }} {{ num(b.count) }}</span>
            <span v-if="!g.by_book.length">—</span>
          </td>
          <td class="px-3 text-left whitespace-nowrap">
            <span v-if="canManage && !g.editable" class="text-[11px] text-slate-400">فقط مدیر {{ g.channel_display }}</span>
            <template v-else-if="canManage">
              <button class="text-xs text-sky-600 px-2" @click="editing = g.id; editName = g.name_fa">تغییر نام</button>
              <button class="text-xs text-sky-600 px-2 disabled:opacity-40" :disabled="!g.customer_count" @click="open(g, 'move')">
                انتقال همه
              </button>
              <button class="text-xs text-red-500 px-2 disabled:opacity-40" :disabled="g.is_system"
                      :title="g.is_system ? 'گروه سیستمی حذف نمی‌شود' : ''" @click="open(g, 'delete')">حذف</button>
            </template>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="acting" class="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3 text-sm" role="dialog">
      <p v-if="acting.mode === 'move'">
        همه‌ی <b>{{ num(acting.group.customer_count) }}</b> مشتری «{{ acting.group.name_fa }}» به کدام گروه بروند؟
      </p>
      <p v-else-if="acting.group.customer_count">
        «{{ acting.group.name_fa }}» <b>{{ num(acting.group.customer_count) }}</b> مشتری دارد.
        پیش از حذف، این مشتری‌ها به کدام گروه منتقل شوند؟
      </p>
      <p v-else>«{{ acting.group.name_fa }}» مشتری ندارد و حذف می‌شود.</p>
      <select v-if="acting.mode === 'move' || acting.group.customer_count" v-model="target"
              class="bg-white rounded-xl border border-slate-200 px-3 py-2" aria-label="گروه مقصد">
        <option value="">گروه مقصد…</option>
        <option v-for="o in groups.filter((x) => x.id !== acting!.group.id)" :key="o.id" :value="o.id">{{ o.name_fa }}</option>
      </select>
      <div class="flex gap-2">
        <button class="rounded-xl px-4 py-2 text-white disabled:opacity-50" :disabled="busy"
                :class="acting.mode === 'delete' ? 'bg-red-500' : 'bg-panel'" @click="confirmAct">
          {{ acting.mode === "delete" ? "حذف گروه" : "انتقال" }}
        </button>
        <button class="rounded-xl px-4 py-2 text-slate-500" @click="acting = null">انصراف</button>
      </div>
    </div>
  </div>
</template>
