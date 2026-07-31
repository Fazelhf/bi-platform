<script setup lang="ts">
/**
 * 2 · Roles & permissions.
 *
 * Two views of the same data: a role list for day-to-day editing, and a
 * matrix that answers the question an auditor actually asks — "who can do
 * what?" — in one screen.
 */
import { computed, onMounted, ref } from "vue";
import { rolesApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import NavIcon from "@/components/NavIcon.vue";
import type { AdminRole, PermissionGroup } from "@/types/admin";

const admin = useAdminStore();

const tab = ref<"list" | "matrix">("list");
const roles = ref<AdminRole[]>([]);
const catalog = ref<PermissionGroup[]>([]);
const loading = ref(true);

const columns: Column[] = [
  { key: "name_fa", label: "نقش", type: "slot" },
  { key: "code", label: "کد" },
  { key: "description", label: "توضیح" },
  { key: "permissions", label: "تعداد دسترسی", type: "slot", align: "center" },
  { key: "user_count", label: "کاربران", type: "number", align: "center" },
  { key: "is_active", label: "وضعیت", type: "slot", align: "center" },
];

async function load() {
  loading.value = true;
  try {
    const data = await rolesApi.matrix();
    roles.value = data.roles;
    catalog.value = data.catalog;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری نقش‌ها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- editor
const editorOpen = ref(false);
const saving = ref(false);
const editing = ref<AdminRole | null>(null);
const form = ref<Record<string, any>>({});
const chosen = ref<string[]>([]);

function openCreate() {
  editing.value = null;
  form.value = { code: "", name_fa: "", description: "", color: "#3b6fed", is_active: true };
  chosen.value = [];
  editorOpen.value = true;
}

function openEdit(role: AdminRole) {
  editing.value = role;
  form.value = {
    code: role.code, name_fa: role.name_fa, description: role.description,
    color: role.color || "#3b6fed", is_active: role.is_active,
  };
  chosen.value = [...(role.permissions ?? [])];
  editorOpen.value = true;
}

async function save() {
  saving.value = true;
  try {
    const payload = { ...form.value, permissions: chosen.value };
    if (editing.value) await rolesApi.patch(editing.value.id, payload);
    else await rolesApi.create(payload);
    toast.success(editing.value ? "نقش به‌روزرسانی شد." : "نقش ساخته شد.");
    editorOpen.value = false;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function clone(role: AdminRole) {
  const code = `${role.code}-copy`;
  if (!(await confirm({
    title: "کپی نقش",
    message: `یک نقش تازه با کد «${code}» و همان دسترسی‌های «${role.name_fa}» ساخته شود؟`,
  }))) return;
  try {
    const created = await rolesApi.clone(role.id, { code, name_fa: `${role.name_fa} (کپی)` });
    toast.success("نقش کپی شد.");
    await load();
    openEdit(created);
  } catch (e) { toast.error(apiError(e)); }
}

async function remove(role: AdminRole) {
  if (!(await confirm({
    title: "حذف نقش",
    message: `«${role.name_fa}» حذف شود؟`,
    danger: true,
  }))) return;
  try {
    await rolesApi.remove(role.id);
    toast.success("نقش حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// -- bulk helpers inside the editor --
function toggleArea(group: PermissionGroup) {
  const codes = group.permissions.map(([c]) => c);
  const allOn = codes.every((c) => chosen.value.includes(c));
  chosen.value = allOn
    ? chosen.value.filter((c) => !codes.includes(c))
    : [...new Set([...chosen.value, ...codes])];
}
function areaState(group: PermissionGroup): "all" | "some" | "none" {
  const codes = group.permissions.map(([c]) => c);
  const on = codes.filter((c) => chosen.value.includes(c)).length;
  return on === 0 ? "none" : on === codes.length ? "all" : "some";
}
function selectViewOnly() {
  chosen.value = catalog.value.flatMap((g) =>
    g.permissions.map(([c]) => c).filter((c) => c.endsWith(".view")),
  );
}

// ---------------------------------------------------------------- matrix
const matrixRoles = computed(() => roles.value.filter((r) => r.is_active));
function has(role: AdminRole, code: string) {
  return (role.permissions ?? []).includes(code);
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader
      title="نقش‌ها و دسترسی‌ها"
      description="دسترسی‌های ریزدانه (RBAC) — هر نقش مجموعه‌ای از مجوزهاست و هر کاربر می‌تواند چند نقش داشته باشد."
    >
      <template #actions>
        <div class="flex bg-surface rounded-xl shadow-soft p-1">
          <button
            v-for="t in (['list', 'matrix'] as const)" :key="t"
            class="px-3 py-1.5 text-sm rounded-lg transition"
            :class="tab === t ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = t"
          >{{ t === "list" ? "فهرست نقش‌ها" : "ماتریس دسترسی" }}</button>
        </div>
        <button
          v-if="admin.can('roles.manage')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ نقش جدید</button>
      </template>
    </PageHeader>

    <!-- ============ List ============ -->
    <DataTable
      v-if="tab === 'list'"
      :columns="columns"
      :rows="roles"
      :loading="loading"
      exportable
      empty-title="نقشی تعریف نشده است"
      empty-hint="با «نقش جدید» اولین نقش سفارشی را بسازید."
      @refresh="load"
      @export="(f) => rolesApi.export(f)"
    >
      <template #cell-name_fa="{ row }">
        <div class="flex items-center gap-2">
          <span class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ background: row.color || '#94a3b8' }"></span>
          <span class="text-ink">{{ row.name_fa }}</span>
          <Badge v-if="row.is_system" tone="info">سیستمی</Badge>
        </div>
      </template>
      <template #cell-permissions="{ row }">
        <Badge tone="neutral">{{ faNum(row.permissions?.length ?? 0) }}</Badge>
      </template>
      <template #cell-is_active="{ row }">
        <Badge :tone="row.is_active ? 'good' : 'neutral'" dot>
          {{ row.is_active ? "فعال" : "غیرفعال" }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button v-if="admin.can('roles.manage')" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <button v-if="admin.can('roles.manage')" class="text-slate-500 hover:text-ink" @click="clone(row)">کپی</button>
          <button
            v-if="admin.can('roles.manage') && !row.is_system"
            class="text-red-500 hover:underline"
            @click="remove(row)"
          >حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- ============ Matrix ============ -->
    <div v-else class="bg-surface rounded-card shadow-soft overflow-hidden">
      <div class="p-4 border-b border-slate-100">
        <h2 class="font-semibold text-ink">ماتریس دسترسی</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          فقط نقش‌های فعال نمایش داده می‌شوند. ادمین ارشد (superuser) همیشه همه دسترسی‌ها را دارد.
        </p>
      </div>
      <div v-if="loading" class="p-8 text-center text-sm text-slate-400">در حال بارگذاری…</div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-slate-50/60">
            <tr class="text-slate-400">
              <th class="text-right font-medium py-2.5 px-3 sticky right-0 bg-slate-50/95 min-w-[220px]">دسترسی</th>
              <th
                v-for="r in matrixRoles" :key="r.id"
                class="font-medium py-2.5 px-2 text-center whitespace-nowrap"
              >
                <span class="block text-ink text-xs">{{ r.name_fa }}</span>
                <span class="block text-[10px] text-slate-400">{{ faNum(r.user_count) }} کاربر</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="group in catalog" :key="group.area">
              <tr class="bg-slate-50/40">
                <td
                  class="py-1.5 px-3 font-semibold text-ink text-xs sticky right-0 bg-slate-50/95"
                  :colspan="1"
                >{{ group.label }}</td>
                <td :colspan="matrixRoles.length"></td>
              </tr>
              <tr
                v-for="[code, label] in group.permissions" :key="code"
                class="border-b border-slate-50 hover:bg-slate-50/50"
              >
                <td class="py-2 px-3 sticky right-0 bg-surface">
                  <span class="text-ink">{{ label }}</span>
                  <span class="block text-[10px] text-slate-400 ltr-nums">{{ code }}</span>
                </td>
                <td v-for="r in matrixRoles" :key="r.id" class="text-center px-2">
                  <NavIcon
                    v-if="has(r, code)" name="check" :size="16"
                    class="inline text-accent-600"
                  />
                  <span v-else class="text-slate-200">—</span>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ============ Editor ============ -->
    <Drawer
      :open="editorOpen"
      :title="editing ? `ویرایش نقش ${editing.name_fa}` : 'نقش جدید'"
      :subtitle="`${faNum(chosen.length)} دسترسی انتخاب شده`"
      width="lg"
      :busy="saving"
      @close="editorOpen = false"
    >
      <div class="space-y-4">
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">کد نقش * (انگلیسی)</span>
            <input
              v-model="form.code" required :disabled="editing?.is_system"
              class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums disabled:opacity-60"
            />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نام نمایشی *</span>
            <input v-model="form.name_fa" required class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">توضیح</span>
            <input v-model="form.description" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">رنگ نشان</span>
            <input v-model="form.color" type="color" class="mt-1 w-full h-10 border border-slate-200 rounded-xl bg-surface" />
          </label>
          <div class="flex items-end pb-1">
            <Toggle v-model="form.is_active" label="نقش فعال است" />
          </div>
        </div>

        <div class="flex items-center justify-between gap-2 pt-2 border-t border-slate-100">
          <p class="text-sm font-semibold text-ink">دسترسی‌ها</p>
          <div class="flex gap-1.5 text-xs">
            <button class="px-2 py-1 rounded-lg bg-slate-100 hover:bg-slate-200" @click="selectViewOnly">فقط خواندنی</button>
            <button
              class="px-2 py-1 rounded-lg bg-slate-100 hover:bg-slate-200"
              @click="chosen = catalog.flatMap((g) => g.permissions.map(([c]) => c))"
            >انتخاب همه</button>
            <button class="px-2 py-1 rounded-lg bg-slate-100 hover:bg-slate-200" @click="chosen = []">حذف همه</button>
          </div>
        </div>

        <div class="space-y-2">
          <section
            v-for="group in catalog" :key="group.area"
            class="border border-slate-200 rounded-xl overflow-hidden"
          >
            <button
              class="w-full flex items-center gap-2 px-3 py-2 bg-slate-50 hover:bg-slate-100 transition text-right"
              @click="toggleArea(group)"
            >
              <span
                class="w-4 h-4 rounded border grid place-items-center shrink-0"
                :class="areaState(group) === 'all'
                  ? 'bg-brand-600 border-brand-600 text-white'
                  : areaState(group) === 'some'
                    ? 'bg-brand-100 border-brand-300'
                    : 'border-slate-300'"
              >
                <NavIcon v-if="areaState(group) === 'all'" name="check" :size="11" />
              </span>
              <span class="text-sm font-medium text-ink flex-1">{{ group.label }}</span>
              <span class="text-[11px] text-slate-400">
                {{ faNum(group.permissions.filter(([c]) => chosen.includes(c)).length) }} /
                {{ faNum(group.permissions.length) }}
              </span>
            </button>
            <div class="p-2 grid sm:grid-cols-2 gap-1">
              <label
                v-for="[code, label] in group.permissions" :key="code"
                class="flex items-center gap-2 px-2 py-1.5 rounded-lg text-sm cursor-pointer hover:bg-slate-50"
              >
                <input v-model="chosen" type="checkbox" :value="code" class="rounded" />
                <span class="text-ink">{{ label }}</span>
                <span class="text-[10px] text-slate-300 ltr-nums mr-auto">{{ code }}</span>
              </label>
            </div>
          </section>
        </div>
      </div>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="editorOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="saving"
          @click="save"
        >{{ saving ? "در حال ذخیره…" : "ذخیره نقش" }}</button>
      </template>
    </Drawer>
  </div>
</template>
