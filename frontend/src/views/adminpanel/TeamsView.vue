<script setup lang="ts">
/** 3 · Teams — org units with a manager, a parent and members. */
import { computed, onMounted, ref } from "vue";
import { teamsApi, usersApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faNum } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import NavIcon from "@/components/NavIcon.vue";
import type { AdminTeam, AdminUser, TeamNode } from "@/types/admin";

const admin = useAdminStore();

const tab = ref<"list" | "tree">("list");
const teams = ref<AdminTeam[]>([]);
const tree = ref<TeamNode[]>([]);
const users = ref<AdminUser[]>([]);
const loading = ref(true);

// Served by the API from the model's choices — see UsersView for why this is
// not written out by hand.
const DEPARTMENTS = computed(() =>
  admin.departments.length
    ? admin.departments.map((d) => ({
      value: d.value,
      label: d.value === "" ? "— بدون بخش" : d.label,
    }))
    : [{ value: "", label: "— بدون بخش" }],
);

const columns: Column[] = [
  { key: "name_fa", label: "تیم" },
  { key: "code", label: "کد" },
  { key: "department_label", label: "بخش" },
  { key: "manager_name", label: "مدیر تیم" },
  { key: "parent_name", label: "تیم بالادست" },
  { key: "member_count", label: "اعضا", type: "number", align: "center" },
  { key: "is_active", label: "وضعیت", type: "slot", align: "center" },
];

async function load() {
  loading.value = true;
  try {
    const [list, hierarchy, people] = await Promise.all([
      teamsApi.list({ page_size: 200 }),
      teamsApi.tree(),
      admin.can("users.view")
        ? usersApi.list({ page_size: 500 })
        : Promise.resolve({ results: [] as AdminUser[] }),
    ]);
    teams.value = list.results;
    tree.value = hierarchy;
    users.value = people.results as AdminUser[];
  } catch (e) {
    toast.error(apiError(e, "بارگذاری تیم‌ها ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- editor
const editorOpen = ref(false);
const saving = ref(false);
const editing = ref<AdminTeam | null>(null);
const form = ref<Record<string, any>>({});
const memberToAdd = ref<number | "">("");

function openCreate() {
  editing.value = null;
  form.value = {
    code: "", name_fa: "", description: "", department: "",
    manager: null, parent: null, is_active: true,
  };
  editorOpen.value = true;
}

function openEdit(team: AdminTeam) {
  editing.value = team;
  form.value = {
    code: team.code, name_fa: team.name_fa, description: team.description,
    department: team.department, manager: team.manager, parent: team.parent,
    is_active: team.is_active,
  };
  memberToAdd.value = "";
  editorOpen.value = true;
}

async function save() {
  saving.value = true;
  try {
    const saved = editing.value
      ? await teamsApi.patch(editing.value.id, form.value)
      : await teamsApi.create(form.value);
    toast.success(editing.value ? "تیم به‌روزرسانی شد." : "تیم ساخته شد.");
    await load();
    editing.value = teams.value.find((t) => t.id === saved.id) ?? null;
    if (!editing.value) editorOpen.value = false;
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

async function addMember() {
  if (!editing.value || !memberToAdd.value) return;
  try {
    await teamsApi.addMember(editing.value.id, Number(memberToAdd.value));
    memberToAdd.value = "";
    await load();
    editing.value = teams.value.find((t) => t.id === editing.value!.id) ?? null;
    toast.success("عضو اضافه شد.");
  } catch (e) { toast.error(apiError(e)); }
}

async function removeMember(userId: number) {
  if (!editing.value) return;
  try {
    await teamsApi.removeMember(editing.value.id, userId);
    await load();
    editing.value = teams.value.find((t) => t.id === editing.value!.id) ?? null;
    toast.success("عضو حذف شد.");
  } catch (e) { toast.error(apiError(e)); }
}

async function remove(team: AdminTeam) {
  if (!(await confirm({
    title: "حذف تیم",
    message: `«${team.name_fa}» حذف شود؟ اعضا حذف نمی‌شوند، فقط عضویتشان برداشته می‌شود.`,
    danger: true,
  }))) return;
  try {
    await teamsApi.remove(team.id);
    toast.success("تیم حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="تیم‌ها" description="ساختار سازمانی: تیم، مدیر تیم، سلسله‌مراتب و اعضا">
      <template #actions>
        <div class="flex bg-surface rounded-xl shadow-soft p-1">
          <button
            v-for="t in (['list', 'tree'] as const)" :key="t"
            class="px-3 py-1.5 text-sm rounded-lg transition"
            :class="tab === t ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = t"
          >{{ t === "list" ? "فهرست" : "چارت سازمانی" }}</button>
        </div>
        <button
          v-if="admin.can('teams.manage')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ تیم جدید</button>
      </template>
    </PageHeader>

    <DataTable
      v-if="tab === 'list'"
      :columns="columns"
      :rows="teams"
      :loading="loading"
      exportable
      empty-title="تیمی تعریف نشده است"
      @refresh="load"
      @export="(f) => teamsApi.export(f)"
    >
      <template #cell-is_active="{ row }">
        <Badge :tone="row.is_active ? 'good' : 'neutral'" dot>
          {{ row.is_active ? "فعال" : "غیرفعال" }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <div class="flex items-center gap-2 text-xs">
          <button class="text-brand-600 hover:underline" @click="openEdit(row)">
            {{ admin.can("teams.manage") ? "ویرایش" : "جزئیات" }}
          </button>
          <button
            v-if="admin.can('teams.manage')"
            class="text-red-500 hover:underline"
            @click="remove(row)"
          >حذف</button>
        </div>
      </template>
    </DataTable>

    <!-- Org chart -->
    <div v-else class="bg-surface rounded-card shadow-soft p-4">
      <p v-if="!tree.length" class="text-sm text-slate-400 py-8 text-center">تیمی ثبت نشده است.</p>
      <ul v-else class="space-y-1.5">
        <!-- Recursive rendering without a helper component: the hierarchy is
             at most a few levels deep in practice. -->
        <li v-for="node in tree" :key="node.id">
          <div class="flex items-center gap-2 p-2.5 rounded-xl bg-slate-50">
            <NavIcon name="team" :size="17" class="text-slate-400 shrink-0" />
            <span class="font-medium text-ink">{{ node.name_fa }}</span>
            <Badge v-if="node.manager_name" tone="neutral">مدیر: {{ node.manager_name }}</Badge>
            <Badge tone="brand">{{ faNum(node.member_count) }} عضو</Badge>
            <Badge v-if="!node.is_active" tone="neutral">غیرفعال</Badge>
          </div>
          <ul v-if="node.children.length" class="mr-6 mt-1.5 space-y-1.5 border-r-2 border-slate-100 pr-3">
            <li v-for="child in node.children" :key="child.id">
              <div class="flex items-center gap-2 p-2 rounded-xl bg-slate-50/60">
                <NavIcon name="team" :size="15" class="text-slate-400 shrink-0" />
                <span class="text-sm text-ink">{{ child.name_fa }}</span>
                <Badge tone="neutral">{{ faNum(child.member_count) }} عضو</Badge>
              </div>
              <ul v-if="child.children.length" class="mr-6 mt-1.5 space-y-1 border-r-2 border-slate-100 pr-3">
                <li
                  v-for="grand in child.children" :key="grand.id"
                  class="text-sm text-slate-600 p-1.5"
                >
                  {{ grand.name_fa }} · {{ faNum(grand.member_count) }} عضو
                </li>
              </ul>
            </li>
          </ul>
        </li>
      </ul>
    </div>

    <!-- ============ Editor ============ -->
    <Drawer
      :open="editorOpen"
      :title="editing ? `تیم ${editing.name_fa}` : 'تیم جدید'"
      :subtitle="editing ? `${faNum(editing.member_count)} عضو` : 'یک واحد سازمانی تازه'"
      :busy="saving"
      @close="editorOpen = false"
    >
      <div class="space-y-4">
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">کد تیم * (انگلیسی)</span>
            <input v-model="form.code" required class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نام تیم *</span>
            <input v-model="form.name_fa" required class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">توضیح</span>
            <input v-model="form.description" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">بخش</span>
            <select v-model="form.department" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option v-for="d in DEPARTMENTS" :key="d.value" :value="d.value">{{ d.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">مدیر تیم</span>
            <select v-model="form.manager" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option :value="null">— بدون مدیر</option>
              <option v-for="u in users" :key="u.id" :value="u.id">{{ u.name }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">تیم بالادست</span>
            <select v-model="form.parent" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option :value="null">— بدون والد</option>
              <option
                v-for="t in teams.filter((x) => x.id !== editing?.id)" :key="t.id" :value="t.id"
              >{{ t.name_fa }}</option>
            </select>
          </label>
          <div class="flex items-end pb-1">
            <Toggle v-model="form.is_active" label="تیم فعال است" />
          </div>
        </div>

        <!-- Members -->
        <section v-if="editing" class="pt-3 border-t border-slate-100">
          <p class="text-sm font-semibold text-ink mb-2">اعضای تیم</p>
          <div v-if="admin.can('teams.members')" class="flex gap-2 mb-3">
            <select v-model="memberToAdd" class="flex-1 border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option value="">افزودن عضو…</option>
              <option
                v-for="u in users.filter((x) => !editing?.members.some((m) => m.user_id === x.id))"
                :key="u.id" :value="u.id"
              >{{ u.name }} ({{ u.username }})</option>
            </select>
            <button
              class="px-3 py-2 text-sm rounded-xl bg-slate-100 hover:bg-slate-200 disabled:opacity-40"
              :disabled="!memberToAdd"
              @click="addMember"
            >افزودن</button>
          </div>
          <p v-if="!editing.members.length" class="text-sm text-slate-400">هنوز عضوی ندارد.</p>
          <ul v-else class="space-y-1">
            <li
              v-for="m in editing.members" :key="m.id"
              class="flex items-center justify-between gap-2 px-3 py-2 rounded-xl bg-slate-50 text-sm"
            >
              <span class="text-ink">
                {{ m.name }}
                <Badge v-if="m.is_lead" tone="brand">سرپرست</Badge>
              </span>
              <button
                v-if="admin.can('teams.members')"
                class="text-xs text-red-500 hover:underline"
                @click="removeMember(m.user_id)"
              >حذف</button>
            </li>
          </ul>
        </section>
        <p v-else class="text-xs text-slate-400">
          پس از ذخیره، می‌توانید اعضای تیم را اضافه کنید.
        </p>
      </div>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="editorOpen = false">بستن</button>
        <button
          v-if="admin.can('teams.manage')"
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="saving"
          @click="save"
        >{{ saving ? "در حال ذخیره…" : "ذخیره" }}</button>
      </template>
    </Drawer>
  </div>
</template>
