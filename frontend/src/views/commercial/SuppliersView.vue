<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { commercialApi, type Supplier } from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import SupplierForm from "@/components/commercial/SupplierForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** تامین‌کنندگان. */
const auth = useAuthStore();
const router = useRouter();

const rows = ref<Supplier[]>([]);
const loading = ref(true);
const error = ref("");
const search = ref("");
const showInactive = ref(false);

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const filtered = computed(() => {
  const q = search.value.trim();
  return rows.value.filter((s) => {
    if (!showInactive.value && !s.is_active) return false;
    if (q && !`${s.name_fa} ${s.contact_name} ${s.mobile} ${s.phone} ${s.activity}`.includes(q))
      return false;
    return true;
  });
});

async function load() {
  loading.value = true;
  try {
    rows.value = await commercialApi.suppliers();
  } finally {
    loading.value = false;
  }
}

onMounted(load);

const editing = ref<Supplier | null>(null);
const showForm = ref(false);

function open(supplier: Supplier | null) {
  editing.value = supplier;
  showForm.value = true;
}

function onSaved() {
  showForm.value = false;
  editing.value = null;
  load();
}

async function remove(supplier: Supplier) {
  const ok = await confirm({
    title: "حذف تامین‌کننده",
    message: `«${supplier.name_fa}» حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await commercialApi.removeSupplier(supplier.id);
    load();
  } catch (e) {
    error.value = apiError(e);
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی نام شرکت، تماس یا فعالیت…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[200px]"
      />
      <label class="flex items-center gap-1.5 text-xs text-slate-500 px-1">
        <input v-model="showInactive" type="checkbox" class="rounded" />
        غیرفعال‌ها
      </label>
      <span class="text-xs text-slate-400 px-2">{{ num(filtered.length) }} تامین‌کننده</span>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="open(null)"
      >+ تامین‌کننده جدید</button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <SupplierForm
      v-if="showForm" :supplier="editing"
      @close="showForm = false" @saved="onSaved"
    />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!filtered.length"
      title="تامین‌کننده‌ای یافت نشد"
      hint="هر شرکتی که از آن قیمت می‌گیرید را اضافه کنید — حتی اگر هنوز از آن خرید نکرده‌اید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <!-- A card per supplier on phones; see OrdersView for the reasoning. -->
      <ul class="md:hidden divide-y divide-slate-100">
        <li
          v-for="s in filtered" :key="`m-${s.id}`"
          class="p-4 active:bg-slate-50 cursor-pointer"
          @click="router.push({ name: 'commercial-supplier', params: { id: s.id } })"
        >
          <p class="text-ink font-medium truncate">
            {{ s.name_fa }}
            <span v-if="!s.is_active" class="text-xs text-slate-400">(غیرفعال)</span>
          </p>
          <p v-if="s.contact_name" class="text-xs text-slate-400 truncate">{{ s.contact_name }}</p>
          <p class="text-xs text-slate-500 mt-1 truncate">{{ s.activity || "—" }}</p>
          <div class="flex items-center justify-between gap-2 mt-1.5 text-xs text-slate-400 ltr-nums">
            <span>{{ s.mobile || s.phone || "—" }}</span>
            <span>{{ num(s.quote_count) }} استعلام · {{ num(s.order_count) }} خرید</span>
          </div>
          <div v-if="canEdit" class="flex gap-2 mt-3" @click.stop>
            <button class="text-xs px-3 py-2 rounded-lg bg-slate-100 text-slate-600" @click="open(s)">ویرایش</button>
            <button class="text-xs px-3 py-2 rounded-lg bg-red-50 text-red-500" @click="remove(s)">حذف</button>
          </div>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[760px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">شرکت</th>
              <th class="text-right font-medium px-3">نوع فعالیت</th>
              <th class="text-right font-medium px-3">تماس</th>
              <th class="text-right font-medium px-3">استعلام</th>
              <th class="text-right font-medium px-3">خرید</th>
              <th class="px-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="s in filtered" :key="s.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'commercial-supplier', params: { id: s.id } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium">
                  {{ s.name_fa }}
                  <span v-if="!s.is_active" class="text-xs text-slate-400">(غیرفعال)</span>
                </p>
                <p class="text-xs text-slate-400">{{ s.contact_name }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ s.activity || "—" }}</td>
              <td class="px-3 text-slate-500 ltr-nums">{{ s.mobile || s.phone || "—" }}</td>
              <td class="px-3 text-slate-500 ltr-nums">{{ num(s.quote_count) }}</td>
              <td class="px-3 text-slate-500 ltr-nums">{{ num(s.order_count) }}</td>
              <td class="px-4 text-left whitespace-nowrap" @click.stop>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-ink px-1.5"
                  @click="open(s)"
                >ویرایش</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                  @click="remove(s)"
                >حذف</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
