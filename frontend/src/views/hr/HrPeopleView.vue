<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { hrApi, type DeleteImpact, type Person } from "@/api/hr";
import { toast } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import FormModal from "@/components/crm/FormModal.vue";
import PickerField from "@/components/PickerField.vue";
import PersonForm from "@/components/hr/PersonForm.vue";
import AccountForm from "@/components/hr/AccountForm.vue";
import { useAuthStore } from "@/stores/auth";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * افراد و بایگانی.
 *
 * Four views of the same people, each answering one question:
 *   فعال — who works here;  بدون سمت — who the chart has forgotten;
 *   بایگانی — who left (kept only so old figures still carry a name);
 *   تکراری — who exists twice under two spellings.
 */
type Tab = "active" | "unplaced" | "archived" | "duplicates";

const route = useRoute();
const router = useRouter();

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "active", label: "فعال", hint: "همه افرادی که در شرکت کار می‌کنند" },
  { key: "unplaced", label: "بدون سمت", hint: "فعال‌اند اما در چارت جایی ندارند — یا سمتشان را بدهید یا بایگانی کنید" },
  { key: "archived", label: "بایگانی", hint: "از شرکت رفته‌اند؛ فقط برای نام در آمار دوره‌های قدیمی نگهداری می‌شوند" },
  { key: "duplicates", label: "نام تکراری", hint: "یک نفر که دو بار با املای متفاوت ثبت شده — تکراری را در اصلی ادغام کنید" },
];

const tab = ref<Tab>((route.query.tab as Tab) || "active");
const rows = ref<Person[]>([]);
const groups = ref<Person[][]>([]);
const activePeople = ref<Person[]>([]);
const loading = ref(true);
const search = ref("");

async function load() {
  loading.value = true;
  try {
    if (tab.value === "duplicates") {
      groups.value = await hrApi.duplicates();
    } else {
      rows.value = await hrApi.people(tab.value);
    }
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(tab, (t) => {
  router.replace({ query: { ...route.query, tab: t } });
  load();
});

const filtered = computed(() => {
  const q = search.value.trim();
  if (!q) return rows.value;
  return rows.value.filter((p) =>
    `${p.full_name_fa} ${p.mobile} ${p.username} ${p.positions.map((x) => `${x.title} ${x.unit}`).join(" ")}`.includes(q),
  );
});

// ---- editing ------------------------------------------------------------
const editing = ref<Person | null>(null);
const showForm = ref(false);
function openForm(p: Person | null) {
  editing.value = p;
  showForm.value = true;
}

// ---- login accounts ----------------------------------------------------
const auth = useAuthStore();
/** Only an administrator makes accounts; everyone here sees who has one. */
const canMakeAccounts = computed(() => auth.isAdminPanelUser || !!auth.me?.is_superuser);
const accountFor = ref<Person | null>(null);

function openProfile(p: Person) {
  if (p.user) router.push({ name: "profile", params: { id: p.user } });
}

async function afterAccount(p: Person) {
  accountFor.value = null;
  toast.success(`حساب «${p.username}» به ${p.full_name_fa} وصل شد.`);
  await load();
}

const accountStats = computed(() => ({
  with: rows.value.filter((p) => p.user).length,
  total: rows.value.length,
}));

// ---- permanent delete: main admin only ---------------------------------
const isRoot = computed(() => !!auth.me?.is_superuser);
const deleting = ref<Person | null>(null);
const impact = ref<DeleteImpact | null>(null);
const deleteConfirm = ref("");
const deleteError = ref("");

async function askDelete(p: Person) {
  deleting.value = p;
  impact.value = null;
  deleteConfirm.value = "";
  deleteError.value = "";
  try {
    impact.value = await hrApi.deletePreview(p.id);
  } catch (e) {
    deleteError.value = apiError(e);
  }
}

const deleteReady = computed(
  () => !!deleting.value && deleteConfirm.value.trim() === deleting.value.full_name_fa.trim(),
);

async function doDelete() {
  if (!deleting.value || !deleteReady.value) {
    deleteError.value = "نام کامل فرد را دقیقا همان‌طور که نوشته شده وارد کنید.";
    return;
  }
  busy.value = true;
  deleteError.value = "";
  try {
    await hrApi.hardDelete(deleting.value.id, deleteConfirm.value.trim());
    toast.success(`«${deleting.value.full_name_fa}» برای همیشه حذف شد.`);
    deleting.value = null;
    await load();
  } catch (e) {
    deleteError.value = apiError(e);
  } finally {
    busy.value = false;
  }
}

// ---- archive / restore -------------------------------------------------
const archiving = ref<Person | null>(null);
const archiveNote = ref("");
const busy = ref(false);

function askArchive(p: Person) {
  archiving.value = p;
  archiveNote.value = "";
}

async function doArchive() {
  if (!archiving.value) return;
  busy.value = true;
  try {
    await hrApi.archive(archiving.value.id, archiveNote.value);
    toast.success(`«${archiving.value.full_name_fa}» بایگانی شد.`);
    archiving.value = null;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    busy.value = false;
  }
}

async function doRestore(p: Person) {
  try {
    await hrApi.restore(p.id);
    toast.success(`«${p.full_name_fa}» از بایگانی خارج شد. حالا می‌توانید در چارت به او سمت بدهید.`);
    await load();
  } catch (e) {
    toast.error(apiError(e));
  }
}

// ---- merge --------------------------------------------------------------
const merging = ref<Person | null>(null);
const mergeInto = ref<number | null>(null);
const mergeError = ref("");

async function askMerge(p: Person, into: number | null = null) {
  merging.value = p;
  mergeInto.value = into;
  mergeError.value = "";
  if (!activePeople.value.length) activePeople.value = await hrApi.people("active");
}

const mergeOptions = computed(() => [...activePeople.value, ...groups.value.flat()]
  .filter((p, i, all) => p.id !== merging.value?.id && all.findIndex((x) => x.id === p.id) === i)
  .map((p) => ({
    value: p.id,
    label: p.full_name_fa,
    hint: p.positions.map((x) => x.title).join("، ") || (p.is_active ? "بدون سمت" : "بایگانی"),
  })));

async function doMerge() {
  if (!merging.value || !mergeInto.value) {
    mergeError.value = "فرد اصلی را انتخاب کنید.";
    return;
  }
  busy.value = true;
  mergeError.value = "";
  try {
    const res = await hrApi.merge(merging.value.id, mergeInto.value);
    toast.success(`ادغام شد؛ همه سوابق به «${res.person.full_name_fa}» منتقل شد.`);
    merging.value = null;
    await load();
  } catch (e) {
    mergeError.value = apiError(e);
  } finally {
    busy.value = false;
  }
}

const currentHint = computed(() => TABS.find((t) => t.key === tab.value)?.hint ?? "");
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <div class="flex flex-wrap gap-1 bg-slate-100 rounded-xl p-1">
        <button
          v-for="t in TABS" :key="t.key"
          class="px-3 py-1.5 rounded-lg text-sm transition-colors"
          :class="tab === t.key ? 'bg-surface text-ink shadow-soft' : 'text-slate-500 hover:text-ink'"
          @click="tab = t.key"
        >{{ t.label }}</button>
      </div>
      <input
        v-if="tab !== 'duplicates'"
        v-model="search" placeholder="جستجوی نام، سمت یا موبایل…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[12rem]"
      />
      <span v-else class="flex-1" />
      <button
        class="border border-slate-200 rounded-xl px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
        @click="router.push({ name: 'hr-chart' })"
      >چارت سازمانی</button>
      <button class="bg-panel text-white rounded-xl px-4 py-2 text-sm" @click="openForm(null)">+ فرد جدید</button>
    </div>

    <p class="text-xs text-slate-400 px-1">
      {{ currentHint }}
      <template v-if="tab === 'active' && accountStats.total">
        · <span :class="accountStats.with < accountStats.total ? 'text-amber-600' : ''">
          {{ num(accountStats.with) }} از {{ num(accountStats.total) }} نفر حساب کاربری دارند
        </span>
      </template>
    </p>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <!-- Duplicates -->
    <template v-else-if="tab === 'duplicates'">
      <EmptyState v-if="!groups.length" icon="✓" title="نام تکراری پیدا نشد" />
      <div v-else class="grid gap-3 md:grid-cols-2">
        <div v-for="(g, gi) in groups" :key="gi" class="bg-surface rounded-card shadow-soft p-4 space-y-2">
          <div
            v-for="p in g" :key="p.id"
            class="flex items-start justify-between gap-3 border-b border-slate-100 last:border-0 pb-2 last:pb-0"
          >
            <div class="min-w-0">
              <p class="font-medium text-ink">
                {{ p.full_name_fa }}
                <span v-if="!p.is_active" class="text-[11px] text-slate-400">(بایگانی)</span>
              </p>
              <p class="text-xs text-slate-400">
                {{ p.positions.map((x) => x.title).join("، ") || "بدون سمت" }}
                · {{ num(p.sales_records) }} رکورد فروش
                <template v-if="p.username"> · {{ p.username }}</template>
              </p>
            </div>
            <div class="flex flex-col gap-1 shrink-0">
              <button
                v-for="other in g.filter((x) => x.id !== p.id)" :key="other.id"
                class="text-xs bg-slate-100 hover:bg-slate-200 rounded-lg px-2 py-1"
                @click="askMerge(p, other.id)"
              >ادغام در این ←</button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <EmptyState
      v-else-if="!filtered.length"
      :title="tab === 'archived' ? 'بایگانی خالی است' : tab === 'unplaced' ? 'همه افراد فعال در چارت جا دارند' : 'فردی ثبت نشده'"
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <ul class="md:hidden divide-y divide-slate-100">
        <li v-for="p in filtered" :key="`m-${p.id}`" class="p-4 space-y-1.5">
          <p class="font-medium text-ink">{{ p.full_name_fa }}</p>
          <p class="text-xs text-slate-500">
            {{ p.positions.map((x) => `${x.title} · ${x.unit}`).join("، ") || "بدون سمت" }}
          </p>
          <div class="flex items-center gap-2 text-xs">
            <button
              v-if="p.user"
              class="text-green-600 hover:underline ltr-nums"
              @click="openProfile(p)"
            >✓ {{ p.username }} — پروفایل</button>
            <template v-else>
              <span class="text-amber-600">✗ حساب کاربری ندارد</span>
              <button
                v-if="canMakeAccounts && p.is_active"
                class="bg-panel text-white rounded-lg px-2 py-1"
                @click="accountFor = p"
              >ساخت حساب</button>
            </template>
          </div>
          <p class="text-xs text-slate-400">
            <template v-if="p.channels.length">برگه فروش: {{ p.channels.join("، ") }} · </template>
            {{ num(p.sales_records) }} رکورد فروش
            <template v-if="p.archived_at"> · بایگانی {{ faDate(p.archived_at) }}</template>
          </p>
          <div class="flex gap-2 pt-1">
            <button class="text-xs px-3 py-2 rounded-lg bg-slate-100 text-slate-600" @click="openForm(p)">ویرایش</button>
            <button v-if="p.is_active" class="text-xs px-3 py-2 rounded-lg bg-amber-50 text-amber-700" @click="askArchive(p)">بایگانی</button>
            <button v-else class="text-xs px-3 py-2 rounded-lg bg-emerald-50 text-emerald-700" @click="doRestore(p)">بازگردانی</button>
            <button class="text-xs px-3 py-2 rounded-lg bg-slate-100 text-slate-600" @click="askMerge(p)">ادغام</button>
            <button v-if="isRoot" class="text-xs px-3 py-2 rounded-lg bg-red-50 text-red-600" @click="askDelete(p)">حذف دائمی</button>
          </div>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[860px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">نام</th>
              <th class="text-right font-medium px-3">سمت در چارت</th>
              <th class="text-right font-medium px-3">برگه فروش</th>
              <th class="text-right font-medium px-3">حساب کاربری</th>
              <th class="text-right font-medium px-3">
                {{ tab === "archived" ? "بایگانی" : "سوابق فروش" }}
              </th>
              <th class="px-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in filtered" :key="p.id" class="border-t border-slate-100 hover:bg-slate-50">
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium">{{ p.full_name_fa }}</p>
                <p v-if="p.mobile" class="text-xs text-slate-400 ltr-nums">{{ p.mobile }}</p>
              </td>
              <td class="px-3 text-xs">
                <span v-if="!p.positions.length" class="text-slate-300">—</span>
                <span
                  v-for="x in p.positions" :key="x.id"
                  class="inline-block bg-slate-100 text-slate-600 rounded-full px-2 py-0.5 ml-1 mb-1"
                >{{ x.title }} · {{ x.unit }}</span>
              </td>
              <td class="px-3 text-xs text-slate-500">{{ p.channels.join("، ") || "—" }}</td>
              <td class="px-3 text-xs whitespace-nowrap">
                <button
                  v-if="p.user"
                  class="text-right hover:underline"
                  :title="`پروفایل ${p.account_name}`"
                  @click="openProfile(p)"
                >
                  <span class="ltr-nums" :class="p.account_active ? 'text-green-600' : 'text-slate-400'">
                    ✓ {{ p.username }}
                  </span>
                  <span class="block text-slate-400">
                    {{ p.account_active ? p.account_role : "حساب غیرفعال" }} · پروفایل ←
                  </span>
                </button>
                <template v-else>
                  <span class="text-amber-600">✗ ندارد</span>
                  <button
                    v-if="canMakeAccounts && p.is_active"
                    class="block mt-1 bg-panel text-white rounded-lg px-2 py-1"
                    @click="accountFor = p"
                  >+ ساخت حساب</button>
                </template>
              </td>
              <td class="px-3 text-xs text-slate-500">
                <template v-if="tab === 'archived'">
                  {{ faDate(p.archived_at) }}
                  <p v-if="p.archive_note" class="text-slate-400">{{ p.archive_note }}</p>
                  <p class="text-slate-400">{{ num(p.sales_records) }} رکورد فروش</p>
                </template>
                <template v-else>{{ num(p.sales_records) }}</template>
              </td>
              <td class="px-4 text-left whitespace-nowrap">
                <button class="text-xs text-slate-400 hover:text-ink px-1.5" @click="openForm(p)">ویرایش</button>
                <button
                  v-if="p.is_active"
                  class="text-xs text-amber-600 hover:bg-amber-50 rounded px-1.5 py-1"
                  @click="askArchive(p)"
                >بایگانی</button>
                <button
                  v-else
                  class="text-xs text-emerald-600 hover:bg-emerald-50 rounded px-1.5 py-1"
                  @click="doRestore(p)"
                >بازگردانی</button>
                <button class="text-xs text-slate-400 hover:text-ink px-1.5" @click="askMerge(p)">ادغام</button>
                <button
                  v-if="isRoot"
                  class="text-xs text-red-500 hover:bg-red-50 rounded px-1.5 py-1"
                  title="فقط ادمین اصلی"
                  @click="askDelete(p)"
                >حذف دائمی</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <PersonForm
      v-if="showForm" :person="editing"
      @close="showForm = false" @saved="showForm = false; load()"
    />

    <AccountForm
      v-if="accountFor" :person="accountFor"
      @close="accountFor = null" @saved="afterAccount"
    />

    <FormModal
      v-if="deleting"
      title="حذف دائمی"
      :subtitle="deleting.full_name_fa"
      :saving="busy"
      :error="deleteError"
      save-label="حذف برای همیشه"
      @close="deleting = null"
      @save="doDelete"
    >
      <p class="text-sm bg-red-50 text-red-700 rounded-xl px-3 py-2">
        این کار برگشت‌پذیر نیست. اگر فقط از شرکت رفته، «بایگانی» درست است؛ حذف دائمی برای
        رکوردی است که نباید وجود می‌داشت.
      </p>

      <div v-if="!impact" class="text-sm text-slate-400">در حال بررسی سوابق…</div>
      <template v-else>
        <div>
          <p class="text-xs font-bold text-red-600 mb-1">همراه او حذف می‌شود</p>
          <ul v-if="impact.deleted.length" class="text-sm text-ink space-y-0.5">
            <li v-for="r in impact.deleted" :key="r.model">
              {{ r.label }}: <b class="ltr-nums">{{ num(r.count) }}</b>
            </li>
          </ul>
          <p v-else class="text-sm text-slate-400">هیچ سابقه‌ای ندارد.</p>
        </div>
        <div v-if="impact.unlinked.length">
          <p class="text-xs font-bold text-slate-500 mb-1">می‌ماند، اما بدون مسئول</p>
          <ul class="text-sm text-slate-600 space-y-0.5">
            <li v-for="r in impact.unlinked" :key="r.model">
              {{ r.label }}: <b class="ltr-nums">{{ num(r.count) }}</b>
            </li>
          </ul>
        </div>
        <p v-if="impact.account" class="text-xs text-slate-500">
          حساب کاربری «{{ impact.account }}» حذف نمی‌شود؛ اگر لازم است از پنل ادمین حذفش کنید.
        </p>
      </template>

      <div>
        <label class="text-xs text-slate-500 mb-1 block">
          برای تایید، نام کامل را بنویسید: <b class="text-ink">{{ deleting.full_name_fa }}</b>
        </label>
        <input
          v-model="deleteConfirm"
          class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-red-300"
          autocomplete="off"
        />
      </div>
    </FormModal>

    <FormModal
      v-if="archiving"
      title="بایگانی فرد"
      :subtitle="archiving.full_name_fa"
      :saving="busy"
      save-label="بایگانی کن"
      @close="archiving = null"
      @save="doArchive"
    >
      <p class="text-sm text-slate-600">
        از همه فهرست‌ها و برگه‌های ورود اطلاعات خارج می‌شود و سمت‌هایش در چارت «نامشخص» می‌شود.
        آمار و سوابق گذشته‌اش دست‌نخورده می‌ماند و هر وقت لازم شد می‌توانید بازگردانید.
      </p>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">دلیل / توضیح</label>
        <input
          v-model="archiveNote"
          class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300"
          placeholder="مثلاً پایان همکاری، شهریور ۱۴۰۵"
        />
      </div>
    </FormModal>

    <FormModal
      v-if="merging"
      title="ادغام فرد تکراری"
      :subtitle="merging.full_name_fa"
      :saving="busy"
      :error="mergeError"
      save-label="ادغام کن"
      @close="merging = null"
      @save="doMerge"
    >
      <p class="text-sm text-slate-600">
        «{{ merging.full_name_fa }}» حذف می‌شود و همه سوابقش — فروش، تارگت، CRM، سمت‌ها و حساب
        کاربری — به فرد اصلی منتقل می‌شود. اگر هر دو برای یک دوره عدد فروش داشته باشند، ادغام انجام نمی‌شود.
      </p>
      <div>
        <label class="text-xs text-slate-500 mb-1 block">فرد اصلی *</label>
        <PickerField v-model="mergeInto" :options="mergeOptions" placeholder="انتخاب کنید…" />
      </div>
    </FormModal>
  </div>
</template>
