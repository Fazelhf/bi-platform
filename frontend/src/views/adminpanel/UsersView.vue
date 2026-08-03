<script setup lang="ts">
/**
 * 1 · User management — create, edit, deactivate, lock, reset passwords,
 * assign roles and teams, and read a user's own activity trail.
 *
 * Destructive actions confirm first and are audited server-side; the buttons
 * themselves only appear when the admin holds the matching permission.
 */
import { computed, onMounted, ref } from "vue";
import { rolesApi, teamsApi, usersApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faDateTime, faNum, timeAgo } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import Timeline from "@/components/admin/Timeline.vue";
import UserAvatar from "@/components/UserAvatar.vue";
import type { AdminRole, AdminTeam, AdminUser } from "@/types/admin";

const admin = useAdminStore();

const rows = ref<AdminUser[]>([]);
const roles = ref<AdminRole[]>([]);
const teams = ref<AdminTeam[]>([]);
const stats = ref<Record<string, any> | null>(null);
const loading = ref(true);
// DataTable is a generic component, so InstanceType<> cannot describe it —
// we only need the one method we call.
const table = ref<{ clearSelection: () => void } | null>(null);

const ROLE_OPTIONS = computed(() =>
  admin.roles.length
    ? admin.roles
    : [
      { value: "admin", label: "ادمین سیستم" },
      { value: "executive", label: "مدیرعامل" },
      { value: "manager", label: "مدیر بخش" },
      { value: "operator", label: "اپراتور" },
      { value: "viewer", label: "بیننده" },
    ],
);
// From the API, which reads the model's own choices. Hard-coding this list is
// what left «مالی» out of the dropdown after it was added to the model, so no
// one could be made a finance manager through the panel at all.
const DEPARTMENTS = computed(() =>
  admin.departments.length
    ? admin.departments.map((d) => ({
      value: d.value,
      label: d.value === "" ? "— بدون بخش" : d.label,
    }))
    : [{ value: "", label: "— بدون بخش" }],
);

const columns: Column[] = [
  { key: "name", label: "کاربر", type: "slot" },
  { key: "role_label", label: "نقش", type: "slot" },
  { key: "department_label", label: "بخش" },
  { key: "admin_role_names", label: "نقش‌های ادمین", type: "slot", sortable: false },
  { key: "team_names", label: "تیم‌ها", type: "slot", sortable: false },
  { key: "is_active", label: "وضعیت", type: "slot", align: "center" },
  { key: "last_login", label: "آخرین ورود", type: "slot" },
];

async function load() {
  loading.value = true;
  try {
    const [users, roleList, teamList, counts] = await Promise.all([
      usersApi.list({ page_size: 500 }),
      admin.can("roles.view") ? rolesApi.list({ page_size: 200 }) : Promise.resolve({ results: [] as AdminRole[] }),
      admin.can("teams.view") ? teamsApi.list({ page_size: 200 }) : Promise.resolve({ results: [] as AdminTeam[] }),
      usersApi.stats(),
    ]);
    rows.value = users.results;
    roles.value = roleList.results as AdminRole[];
    teams.value = teamList.results as AdminTeam[];
    stats.value = counts;
  } catch (e) {
    toast.error(apiError(e, "بارگذاری کاربران ناموفق بود."));
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// ---------------------------------------------------------------- editor
const editorOpen = ref(false);
const saving = ref(false);
const editing = ref<AdminUser | null>(null);
const form = ref<Record<string, any>>({});
const formRoles = ref<number[]>([]);
const formTeams = ref<number[]>([]);

function blank() {
  return {
    username: "", display_name_fa: "", job_title_fa: "", email: "", phone: "",
    role: "viewer", department: "", is_active: true, admin_access: false, password: "",
  };
}

function openCreate() {
  editing.value = null;
  form.value = blank();
  formRoles.value = [];
  formTeams.value = [];
  editorOpen.value = true;
}

function openEdit(user: AdminUser) {
  editing.value = user;
  form.value = {
    username: user.username, display_name_fa: user.display_name_fa,
    job_title_fa: user.job_title_fa, email: user.email, phone: user.phone,
    role: user.role, department: user.department, is_active: user.is_active,
    admin_access: user.admin_access, password: "",
  };
  formRoles.value = [...user.admin_role_ids];
  formTeams.value = [...user.team_ids];
  editorOpen.value = true;
}

async function save() {
  saving.value = true;
  try {
    const payload: Record<string, any> = { ...form.value };
    if (!payload.password) delete payload.password;

    const user = editing.value
      ? await usersApi.patch(editing.value.id, payload)
      : await usersApi.create(payload);

    // Role/team membership are their own endpoints, so they are applied only
    // when they actually changed — keeps the audit log meaningful.
    const before = editing.value;
    const rolesChanged = !before ||
      formRoles.value.slice().sort().join() !== before.admin_role_ids.slice().sort().join();
    const teamsChanged = !before ||
      formTeams.value.slice().sort().join() !== before.team_ids.slice().sort().join();
    if (admin.can("roles.assign") && rolesChanged) {
      await usersApi.assignRoles(user.id, formRoles.value);
    }
    if (admin.can("teams.members") && teamsChanged) {
      await usersApi.assignTeams(user.id, formTeams.value);
    }

    toast.success(editing.value ? "کاربر به‌روزرسانی شد." : "کاربر ایجاد شد.");
    editorOpen.value = false;
    await load();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    saving.value = false;
  }
}

// ---------------------------------------------------------------- actions
async function toggleActive(user: AdminUser) {
  const activating = !user.is_active;
  if (!activating && !(await confirm({
    title: "غیرفعال کردن کاربر",
    message: `«${user.name}» دیگر نمی‌تواند وارد سامانه شود. ادامه می‌دهید؟`,
    danger: true,
  }))) return;
  try {
    await usersApi.setActive(user.id, activating);
    toast.success(activating ? "کاربر فعال شد." : "کاربر غیرفعال شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function toggleLock(user: AdminUser) {
  try {
    if (user.is_locked) {
      await usersApi.unlock(user.id);
      toast.success("قفل حساب برداشته شد.");
    } else {
      if (!(await confirm({
        title: "قفل کردن حساب",
        message: `«${user.name}» تا باز شدن قفل نمی‌تواند وارد شود و نشست‌های فعلی‌اش بسته می‌شود.`,
        danger: true,
      }))) return;
      await usersApi.lock(user.id, "قفل توسط مدیر سیستم");
      toast.success("حساب قفل شد.");
    }
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

const newPassword = ref<{ user: string; value: string } | null>(null);

async function resetPassword(user: AdminUser) {
  if (!(await confirm({
    title: "بازنشانی رمز عبور",
    message: `یک رمز تصادفی برای «${user.name}» ساخته می‌شود و نشست‌های فعلی‌اش بسته می‌شود.`,
  }))) return;
  try {
    const result = await usersApi.resetPassword(user.id, { must_change: true });
    newPassword.value = { user: user.name, value: result.password ?? "" };
  } catch (e) { toast.error(apiError(e)); }
}

async function forceLogout(user: AdminUser) {
  if (!(await confirm({
    title: "پایان نشست‌ها",
    message: `همه نشست‌های «${user.name}» بسته شود؟ باید دوباره وارد شود.`,
  }))) return;
  try {
    await usersApi.forceLogout(user.id);
    toast.success("نشست‌ها بسته شد.");
  } catch (e) { toast.error(apiError(e)); }
}

async function remove(user: AdminUser) {
  if (!(await confirm({
    title: "حذف کاربر",
    message: `«${user.name}» برای همیشه حذف شود؟ این عمل قابل بازگشت نیست.`,
    danger: true,
  }))) return;
  try {
    await usersApi.remove(user.id);
    toast.success("کاربر حذف شد.");
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- bulk
async function bulkActive(ids: number[], isActive: boolean) {
  if (!(await confirm({
    title: isActive ? "فعال کردن گروهی" : "غیرفعال کردن گروهی",
    message: `${faNum(ids.length)} کاربر ${isActive ? "فعال" : "غیرفعال"} شوند؟`,
    danger: !isActive,
  }))) return;
  try {
    const result = await usersApi.bulkUpdate(ids, { is_active: isActive });
    toast.success(`${faNum(result.updated)} کاربر به‌روزرسانی شد.`);
    if (result.errors.length) toast.error(`${faNum(result.errors.length)} مورد ناموفق بود.`);
    table.value?.clearSelection();
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

async function bulkDelete(ids: number[]) {
  if (!(await confirm({
    title: "حذف گروهی",
    message: `${faNum(ids.length)} کاربر حذف شوند؟ این عمل قابل بازگشت نیست.`,
    danger: true,
  }))) return;
  try {
    const result = await usersApi.bulkDelete(ids);
    toast.success(`${faNum(result.deleted)} کاربر حذف شد.`);
    if (result.errors.length) toast.error(`${faNum(result.errors.length)} مورد حذف نشد.`);
    table.value?.clearSelection();
    await load();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- activity
const activityOpen = ref(false);
const activityUser = ref<AdminUser | null>(null);
const activity = ref<{ audit: any[]; logins: any[]; permissions: string[] } | null>(null);

async function openActivity(user: AdminUser) {
  activityUser.value = user;
  activity.value = null;
  activityOpen.value = true;
  try {
    activity.value = await usersApi.activity(user.id);
  } catch (e) { toast.error(apiError(e)); }
}

/** Your own row: the panel never offers actions that would sign you out. */
function isSelf(row: AdminUser): boolean {
  return row.id === admin.user?.id;
}

async function copyPassword() {
  if (!newPassword.value) return;
  try {
    await navigator.clipboard.writeText(newPassword.value.value);
    toast.success("رمز کپی شد.");
  } catch {
    toast.error("کپی خودکار ممکن نشد؛ رمز را دستی بردارید.");
  }
}

const activityTimeline = computed(() =>
  (activity.value?.audit ?? []).map((a: any) => ({
    kind: "audit", action: a.action, actor: a.display_name || a.username || "—",
    text: `${a.action} · ${a.object_repr || a.model_label}`, at: a.created_at,
  })),
);
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="مدیریت کاربران" description="ایجاد، ویرایش، قفل و بازنشانی حساب‌های سامانه">
      <template #actions>
        <button
          v-if="admin.can('users.create')"
          class="text-sm px-3 py-1.5 rounded-xl bg-brand-600 text-white hover:bg-brand-700 transition"
          @click="openCreate"
        >+ کاربر جدید</button>
      </template>
    </PageHeader>

    <div v-if="stats" class="grid grid-cols-2 lg:grid-cols-5 gap-3">
      <StatCard label="کل کاربران" :value="faNum(stats.total)" icon="users" tone="brand" />
      <StatCard label="فعال" :value="faNum(stats.active)" icon="check" tone="good" />
      <StatCard label="غیرفعال" :value="faNum(stats.inactive)" icon="close" />
      <StatCard label="قفل‌شده" :value="faNum(stats.locked)" icon="lock" :tone="stats.locked ? 'bad' : 'neutral'" />
      <StatCard label="ادمین سیستم" :value="faNum(stats.admins)" icon="shield" />
    </div>

    <DataTable
      ref="table"
      :columns="columns"
      :rows="rows"
      :loading="loading"
      selectable
      exportable
      :page-size="20"
      search-placeholder="نام، نام کاربری، ایمیل…"
      empty-title="کاربری ثبت نشده است"
      @refresh="load"
      @export="(f) => usersApi.export(f)"
    >
      <template #bulk="{ ids }">
        <button
          v-if="admin.can('users.edit')"
          class="text-xs px-2.5 py-1 rounded-lg bg-surface border border-slate-200 hover:bg-slate-50"
          @click="bulkActive(ids, true)"
        >فعال کردن</button>
        <button
          v-if="admin.can('users.edit')"
          class="text-xs px-2.5 py-1 rounded-lg bg-surface border border-slate-200 hover:bg-slate-50"
          @click="bulkActive(ids, false)"
        >غیرفعال کردن</button>
        <button
          v-if="admin.can('users.delete')"
          class="text-xs px-2.5 py-1 rounded-lg bg-red-500 text-white hover:bg-red-600"
          @click="bulkDelete(ids)"
        >حذف</button>
      </template>

      <template #cell-name="{ row }">
        <div class="flex items-center gap-2.5 min-w-0">
          <UserAvatar
            :name="row.name" :initials="row.name?.slice(0, 2)"
            :color="row.avatar_color" :image="row.avatar_image"
            :online="row.is_online" :size="32"
          />
          <div class="min-w-0">
            <p class="text-ink truncate">{{ row.name }}</p>
            <p class="text-[11px] text-slate-400 truncate ltr-nums">{{ row.username }}</p>
          </div>
        </div>
      </template>

      <template #cell-role_label="{ row }">
        <div class="flex items-center gap-1 flex-wrap">
          <span>{{ row.role_label }}</span>
          <Badge v-if="row.is_superuser" tone="brand">ارشد</Badge>
          <Badge v-else-if="row.is_admin_panel_user" tone="info">پنل</Badge>
        </div>
      </template>

      <template #cell-admin_role_names="{ row }">
        <span v-if="!row.admin_role_names.length" class="text-slate-300">—</span>
        <div v-else class="flex flex-wrap gap-1">
          <Badge v-for="n in row.admin_role_names" :key="n" tone="neutral">{{ n }}</Badge>
        </div>
      </template>

      <template #cell-team_names="{ row }">
        <span v-if="!row.team_names.length" class="text-slate-300">—</span>
        <span v-else class="text-xs text-slate-500">{{ row.team_names.join("، ") }}</span>
      </template>

      <template #cell-is_active="{ row }">
        <Badge v-if="row.is_locked" tone="bad" dot>قفل</Badge>
        <Badge v-else-if="row.is_active" tone="good" dot>فعال</Badge>
        <Badge v-else tone="neutral" dot>غیرفعال</Badge>
      </template>

      <template #cell-last_login="{ row }">
        <span class="text-xs text-slate-500">{{ row.last_login ? timeAgo(row.last_login) : "—" }}</span>
      </template>

      <!-- Actions that would lock you out of the panel you are standing in
           (password reset, lock, deactivate, force-logout, delete) are simply
           not offered on your own row — the API refuses them too. -->
      <template #actions="{ row }">
        <div class="flex items-center gap-1.5 text-xs">
          <button class="text-slate-400 hover:text-ink" title="فعالیت کاربر" @click="openActivity(row)">تاریخچه</button>
          <button v-if="admin.can('users.edit')" class="text-brand-600 hover:underline" @click="openEdit(row)">ویرایش</button>
          <template v-if="!isSelf(row)">
            <button
              v-if="admin.can('users.password')"
              class="text-slate-500 hover:text-ink" title="بازنشانی رمز"
              @click="resetPassword(row)"
            >رمز</button>
            <button
              v-if="admin.can('users.lock')"
              :class="row.is_locked ? 'text-accent-600' : 'text-amber-600'"
              class="hover:underline"
              @click="toggleLock(row)"
            >{{ row.is_locked ? "بازکردن" : "قفل" }}</button>
            <button
              v-if="admin.can('users.edit')"
              class="text-slate-500 hover:text-ink"
              @click="toggleActive(row)"
            >{{ row.is_active ? "غیرفعال" : "فعال" }}</button>
            <button
              v-if="admin.can('security.sessions')"
              class="text-slate-400 hover:text-ink" title="پایان نشست‌ها"
              @click="forceLogout(row)"
            >خروج</button>
            <button v-if="admin.can('users.delete')" class="text-red-500 hover:underline" @click="remove(row)">حذف</button>
          </template>
          <span v-else class="text-slate-300" title="روی حساب خودتان در دسترس نیست">حساب شما</span>
        </div>
      </template>
    </DataTable>

    <!-- ============ Editor ============ -->
    <Drawer
      :open="editorOpen"
      :title="editing ? `ویرایش ${editing.name}` : 'کاربر جدید'"
      :subtitle="editing ? editing.username : 'یک حساب تازه برای سامانه بسازید'"
      :busy="saving"
      @close="editorOpen = false"
    >
      <form class="space-y-4" @submit.prevent="save">
        <div class="grid sm:grid-cols-2 gap-3">
          <label class="block">
            <span class="text-xs text-slate-500">نام کاربری *</span>
            <input v-model="form.username" required class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نام نمایشی</span>
            <input v-model="form.display_name_fa" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">سمت</span>
            <input v-model="form.job_title_fa" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">تلفن</span>
            <input v-model="form.phone" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">ایمیل</span>
            <input v-model="form.email" type="email" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums" />
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">نقش پایه</span>
            <select v-model="form.role" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option v-for="o in ROLE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </label>
          <label class="block">
            <span class="text-xs text-slate-500">بخش</span>
            <select v-model="form.department" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
              <option v-for="o in DEPARTMENTS" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </label>
          <label class="block sm:col-span-2">
            <span class="text-xs text-slate-500">
              {{ editing ? "رمز عبور جدید (خالی = بدون تغییر)" : "رمز عبور *" }}
            </span>
            <input
              v-model="form.password" type="password" :required="!editing"
              autocomplete="new-password"
              class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums"
            />
          </label>
        </div>

        <div class="space-y-2.5 pt-1">
          <Toggle v-model="form.is_active" label="حساب فعال است" hint="غیرفعال‌ها نمی‌توانند وارد شوند." />
          <Toggle
            v-model="form.admin_access"
            label="دسترسی به پنل مدیریت"
            hint="فقط برای کسانی که باید سامانه را مدیریت کنند — مدیرعامل به‌صورت پیش‌فرض دسترسی ندارد."
          />
        </div>

        <div v-if="roles.length && admin.can('roles.assign')">
          <p class="text-xs text-slate-500 mb-1.5">نقش‌های ادمین</p>
          <div class="flex flex-wrap gap-1.5">
            <label
              v-for="r in roles" :key="r.id"
              class="flex items-center gap-1.5 border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs cursor-pointer hover:bg-slate-50"
              :class="{ 'bg-brand-50 border-brand-200 text-brand-700': formRoles.includes(r.id) }"
            >
              <input v-model="formRoles" type="checkbox" :value="r.id" class="rounded" />
              {{ r.name_fa }}
            </label>
          </div>
        </div>

        <div v-if="teams.length && admin.can('teams.members')">
          <p class="text-xs text-slate-500 mb-1.5">عضویت در تیم‌ها</p>
          <div class="flex flex-wrap gap-1.5">
            <label
              v-for="t in teams" :key="t.id"
              class="flex items-center gap-1.5 border border-slate-200 rounded-xl px-2.5 py-1.5 text-xs cursor-pointer hover:bg-slate-50"
              :class="{ 'bg-brand-50 border-brand-200 text-brand-700': formTeams.includes(t.id) }"
            >
              <input v-model="formTeams" type="checkbox" :value="t.id" class="rounded" />
              {{ t.name_fa }}
            </label>
          </div>
        </div>
      </form>

      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="editorOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="saving"
          @click="save"
        >{{ saving ? "در حال ذخیره…" : "ذخیره" }}</button>
      </template>
    </Drawer>

    <!-- ============ Activity ============ -->
    <Drawer
      :open="activityOpen"
      :title="`فعالیت ${activityUser?.name ?? ''}`"
      subtitle="رخدادها، ورودها و دسترسی‌های مؤثر"
      width="lg"
      @close="activityOpen = false"
    >
      <div v-if="!activity" class="text-sm text-slate-400 py-8 text-center">در حال بارگذاری…</div>
      <div v-else class="space-y-5">
        <section>
          <h3 class="font-semibold text-ink text-sm mb-2">دسترسی‌های مؤثر</h3>
          <div v-if="activity.permissions.length" class="flex flex-wrap gap-1.5">
            <Badge v-for="p in activity.permissions" :key="p" tone="neutral">
              {{ admin.permissionLabels[p] || p }}
            </Badge>
          </div>
          <p v-else class="text-sm text-slate-400">هیچ دسترسی ادمینی ندارد.</p>
        </section>

        <section>
          <h3 class="font-semibold text-ink text-sm mb-2">تاریخچه ورود</h3>
          <div v-if="!activity.logins.length" class="text-sm text-slate-400">ورودی ثبت نشده است.</div>
          <ul v-else class="space-y-1.5">
            <li
              v-for="l in activity.logins.slice(0, 15)" :key="l.id"
              class="flex items-center justify-between gap-2 text-xs border-b border-slate-50 pb-1.5"
            >
              <span class="flex items-center gap-2">
                <Badge :tone="l.success ? 'good' : 'bad'" dot>{{ l.success ? "موفق" : "ناموفق" }}</Badge>
                <span class="text-slate-500">{{ l.reason_fa }}</span>
              </span>
              <span class="text-slate-400 ltr-nums">{{ l.ip_address || "—" }} · {{ faDateTime(l.created_at) }}</span>
            </li>
          </ul>
        </section>

        <section>
          <h3 class="font-semibold text-ink text-sm mb-2">رخدادهای سامانه</h3>
          <Timeline :items="activityTimeline" empty="این کاربر تغییری ثبت نکرده است." />
        </section>
      </div>
    </Drawer>

    <!-- ============ Generated password ============ -->
    <Drawer
      :open="!!newPassword"
      title="رمز عبور جدید"
      subtitle="این رمز فقط همین یک بار نمایش داده می‌شود"
      width="sm"
      @close="newPassword = null"
    >
      <p class="text-sm text-slate-500 mb-3">
        رمز تازه برای <span class="font-semibold text-ink">{{ newPassword?.user }}</span>.
        کاربر در ورود بعدی باید آن را تغییر دهد.
      </p>
      <div class="flex items-center gap-2">
        <code class="flex-1 bg-slate-100 rounded-xl px-3 py-2.5 text-sm ltr-nums select-all">
          {{ newPassword?.value }}
        </code>
        <button
          class="px-3 py-2.5 text-sm rounded-xl bg-slate-100 hover:bg-slate-200"
          @click="copyPassword"
        >کپی</button>
      </div>
      <template #footer>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
          @click="newPassword = null; load()"
        >متوجه شدم</button>
      </template>
    </Drawer>
  </div>
</template>
