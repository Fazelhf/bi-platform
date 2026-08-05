<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { commercialApi, type Material, type MaterialCategory } from "@/api/commercial";
import { useAuthStore } from "@/stores/auth";
import { useMoney, loadMoneySettings } from "@/composables/useMoney";
import { confirm } from "@/composables/useUi";
import { apiError } from "@/components/crm/formError";
import { num } from "@/utils/format";
import MaterialForm from "@/components/commercial/MaterialForm.vue";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/** کالاهای مصرفی کارخانه. */
const auth = useAuthStore();
const router = useRouter();
const { exact } = useMoney();

const rows = ref<Material[]>([]);
const categories = ref<MaterialCategory[]>([]);
const loading = ref(true);
const error = ref("");
const search = ref("");
const category = ref<number | "">("");
const showInactive = ref(false);

const canEdit = computed(
  () => auth.department === "commercial" || !!auth.me?.is_superuser,
);

const filtered = computed(() => {
  const q = search.value.trim();
  return rows.value.filter((m) => {
    if (!showInactive.value && !m.is_active) return false;
    if (category.value !== "" && m.category !== category.value) return false;
    if (q && !`${m.name_fa} ${m.code} ${m.note}`.includes(q)) return false;
    return true;
  });
});

async function load() {
  loading.value = true;
  try {
    [rows.value, categories.value] = await Promise.all([
      commercialApi.materials(),
      commercialApi.categories(),
    ]);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => { await loadMoneySettings(); await load(); });

const editing = ref<Material | null>(null);
const showForm = ref(false);

function open(material: Material | null) {
  editing.value = material;
  showForm.value = true;
}

function onSaved() {
  showForm.value = false;
  editing.value = null;
  load();
}

async function remove(material: Material) {
  const ok = await confirm({
    title: "حذف کالا",
    message: `«${material.name_fa}» حذف شود؟`,
    danger: true,
  });
  if (!ok) return;
  try {
    await commercialApi.removeMaterial(material.id);
    load();
  } catch (e) {
    // The server refuses when the material has purchases behind it and says
    // to deactivate instead; showing that beats a silent no-op.
    error.value = apiError(e);
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="bg-surface rounded-card shadow-soft p-3 flex flex-wrap items-center gap-2">
      <input
        v-model="search" placeholder="جستجوی نام یا کد کالا…"
        class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300 flex-1 min-w-[200px]"
      />
      <select v-model="category" class="bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none">
        <option value="">همه دسته‌ها</option>
        <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.name_fa }}</option>
      </select>
      <label class="flex items-center gap-1.5 text-xs text-slate-500 px-1">
        <input v-model="showInactive" type="checkbox" class="rounded" />
        غیرفعال‌ها
      </label>
      <span class="text-xs text-slate-400 px-2">{{ num(filtered.length) }} کالا</span>
      <button
        v-if="canEdit"
        class="bg-panel text-white rounded-xl px-4 py-2 text-sm shrink-0"
        @click="open(null)"
      >+ کالای جدید</button>
    </div>

    <p
      v-if="error"
      class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line"
    >{{ error }}</p>

    <MaterialForm
      v-if="showForm" :material="editing"
      @close="showForm = false" @saved="onSaved"
    />

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 8" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!filtered.length"
      title="کالایی یافت نشد"
      hint="کالاهای مصرفی کارخانه را اینجا اضافه کنید تا بتوانید برایشان استعلام بگیرید."
    />

    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm min-w-[720px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">کالا</th>
              <th class="text-right font-medium px-3">دسته</th>
              <th class="text-right font-medium px-3">واحد</th>
              <th class="text-right font-medium px-3">حداقل موجودی</th>
              <th class="text-right font-medium px-3">آخرین قیمت</th>
              <th class="text-right font-medium px-3">تعداد خرید</th>
              <th class="px-4"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="m in filtered" :key="m.id"
              class="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
              @click="router.push({ name: 'commercial-material', params: { id: m.id } })"
            >
              <td class="px-4 py-2.5">
                <p class="text-ink font-medium">
                  {{ m.name_fa }}
                  <span v-if="!m.is_active" class="text-xs text-slate-400">(غیرفعال)</span>
                </p>
                <p class="text-xs text-slate-400 ltr-nums">{{ m.code }}</p>
              </td>
              <td class="px-3 text-slate-500">{{ m.category_name || "—" }}</td>
              <td class="px-3 text-slate-500">{{ m.unit_label }}</td>
              <td class="px-3 text-slate-500 ltr-nums">{{ num(m.min_stock) }}</td>
              <td class="px-3 text-ink ltr-nums">
                {{ Number(m.last_price_rial) ? exact(m.last_price_rial) : "—" }}
              </td>
              <td class="px-3 text-slate-500 ltr-nums">{{ num(m.order_count) }}</td>
              <td class="px-4 text-left whitespace-nowrap" @click.stop>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-ink px-1.5"
                  @click="open(m)"
                >ویرایش</button>
                <button
                  v-if="canEdit"
                  class="text-xs text-slate-400 hover:text-red-500 px-1.5"
                  @click="remove(m)"
                >حذف</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
