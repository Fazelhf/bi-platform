<script setup lang="ts">
/**
 * 8 · Security — password policy, account locks, live sessions, IP rules,
 * API tokens, 2FA state and the login history.
 */
import { onMounted, ref } from "vue";
import { loginEventsApi, securityApi, usersApi } from "@/api/admin";
import { useAdminStore } from "@/stores/admin";
import { confirm, toast } from "@/composables/useUi";
import { apiError, faDateTime, faNum, timeAgo } from "@/utils/adminFormat";
import DataTable, { type Column } from "@/components/admin/DataTable.vue";
import Drawer from "@/components/admin/Drawer.vue";
import PageHeader from "@/components/admin/PageHeader.vue";
import StatCard from "@/components/admin/StatCard.vue";
import Badge from "@/components/admin/Badge.vue";
import Toggle from "@/components/admin/Toggle.vue";
import type {
  AdminUser, ApiTokenRow, IPRule, LoginEventRow,
  PasswordPolicy, SecurityOverview, SessionRow,
} from "@/types/admin";

const admin = useAdminStore();

const tab = ref<"overview" | "sessions" | "ip" | "tokens" | "logins">("overview");
const overview = ref<SecurityOverview | null>(null);
const policy = ref<PasswordPolicy | null>(null);
const sessions = ref<SessionRow[]>([]);
const ipRules = ref<IPRule[]>([]);
const tokens = ref<ApiTokenRow[]>([]);
const logins = ref<LoginEventRow[]>([]);
const loginTotal = ref(0);
const users = ref<AdminUser[]>([]);
const loading = ref(true);
const savingPolicy = ref(false);

const canManage = () => admin.can("security.manage");

async function loadOverview() {
  try {
    overview.value = await securityApi.overview();
    policy.value = { ...overview.value.policy };
  } catch (e) { toast.error(apiError(e)); }
}
async function loadSessions() { sessions.value = await securityApi.sessions(); }
async function loadIpRules() {
  ipRules.value = (await securityApi.ipRules.list({ page_size: 200 })).results;
}
async function loadTokens() {
  tokens.value = (await securityApi.tokens.list({ page_size: 200 })).results;
}
async function loadLogins(params: Record<string, any> = {}) {
  const data = await loginEventsApi.list({ page_size: 25, ...params });
  logins.value = data.results;
  loginTotal.value = data.count;
}

onMounted(async () => {
  loading.value = true;
  try {
    await Promise.all([
      loadOverview(),
      loadSessions(),
      loadIpRules(),
      admin.can("security.tokens") ? loadTokens() : Promise.resolve(),
      loadLogins(),
      admin.can("users.view")
        ? usersApi.list({ page_size: 500 }).then((d) => (users.value = d.results))
        : Promise.resolve(),
    ]);
  } catch (e) {
    toast.error(apiError(e, "بارگذاری بخش امنیت ناموفق بود."));
  } finally {
    loading.value = false;
  }
});

// ---------------------------------------------------------------- policy
async function savePolicy() {
  if (!policy.value) return;
  savingPolicy.value = true;
  try {
    policy.value = await securityApi.savePolicy(policy.value);
    toast.success("سیاست امنیتی ذخیره شد.");
    await loadOverview();
  } catch (e) {
    toast.error(apiError(e));
  } finally {
    savingPolicy.value = false;
  }
}

// ---------------------------------------------------------------- locks
async function unlock(userId: number) {
  try {
    await usersApi.unlock(userId);
    toast.success("قفل برداشته شد.");
    await loadOverview();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- sessions
const sessionColumns: Column[] = [
  { key: "name", label: "کاربر" },
  { key: "username", label: "نام کاربری" },
  { key: "role", label: "نقش" },
  { key: "ip_address", label: "IP" },
  { key: "since", label: "شروع نشست", type: "slot" },
  { key: "last_seen", label: "آخرین فعالیت", type: "slot" },
];

async function endSession(row: SessionRow) {
  if (!(await confirm({
    title: "پایان نشست",
    message: `نشست‌های «${row.name}» بسته شود؟`,
    danger: true,
  }))) return;
  try {
    await securityApi.endSessions({ user_ids: [row.user_id] });
    toast.success("نشست بسته شد.");
    await loadSessions();
  } catch (e) { toast.error(apiError(e)); }
}

async function endAllSessions() {
  if (!(await confirm({
    title: "خروج اجباری همه",
    message: "همه کاربران (به‌جز خودتان) از سامانه خارج می‌شوند و باید دوباره وارد شوند.",
    danger: true,
  }))) return;
  try {
    const result = await securityApi.endSessions({ all: true });
    toast.success(`${faNum(result.logged_out)} کاربر خارج شد.`);
    await loadSessions();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- IP rules
const ipColumns: Column[] = [
  { key: "mode", label: "نوع", type: "slot", align: "center" },
  { key: "cidr", label: "آدرس / محدوده" },
  { key: "note", label: "توضیح" },
  { key: "is_active", label: "فعال", type: "bool", align: "center" },
  { key: "created_at", label: "ایجاد", type: "date" },
];

const ipOpen = ref(false);
const ipForm = ref({ mode: "deny", cidr: "", note: "", is_active: true });

async function saveIpRule() {
  try {
    await securityApi.ipRules.create(ipForm.value);
    toast.success("قاعده ثبت شد.");
    ipOpen.value = false;
    ipForm.value = { mode: "deny", cidr: "", note: "", is_active: true };
    await Promise.all([loadIpRules(), loadOverview()]);
  } catch (e) { toast.error(apiError(e)); }
}

async function removeIpRule(rule: IPRule) {
  if (!(await confirm({ title: "حذف قاعده", message: `«${rule.cidr}» حذف شود؟`, danger: true }))) return;
  try {
    await securityApi.ipRules.remove(rule.id);
    await Promise.all([loadIpRules(), loadOverview()]);
    toast.success("قاعده حذف شد.");
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- tokens
const tokenColumns: Column[] = [
  { key: "name", label: "نام" },
  { key: "user_name", label: "کاربر" },
  { key: "prefix", label: "پیشوند" },
  { key: "expires_at", label: "انقضا", type: "date" },
  { key: "last_used_at", label: "آخرین استفاده", type: "datetime" },
  { key: "is_active", label: "وضعیت", type: "slot", align: "center" },
];

const tokenOpen = ref(false);
const tokenForm = ref<{ name: string; user: number | ""; expires_at: string }>({
  name: "", user: "", expires_at: "",
});
const issuedToken = ref<string | null>(null);

async function createToken() {
  try {
    const payload: Record<string, any> = { name: tokenForm.value.name, user: tokenForm.value.user };
    if (tokenForm.value.expires_at) payload.expires_at = tokenForm.value.expires_at;
    const created = await securityApi.tokens.create(payload);
    issuedToken.value = (created as ApiTokenRow).token ?? null;
    tokenOpen.value = false;
    tokenForm.value = { name: "", user: "", expires_at: "" };
    await loadTokens();
  } catch (e) { toast.error(apiError(e)); }
}

async function revokeToken(token: ApiTokenRow) {
  if (!(await confirm({
    title: "ابطال توکن",
    message: `«${token.name}» از کار می‌افتد. ادامه؟`,
    danger: true,
  }))) return;
  try {
    await securityApi.revokeToken(token.id);
    toast.success("توکن باطل شد.");
    await loadTokens();
  } catch (e) { toast.error(apiError(e)); }
}

// ---------------------------------------------------------------- logins
const loginColumns: Column[] = [
  { key: "created_at", label: "زمان", type: "datetime" },
  { key: "username_attempted", label: "نام کاربری" },
  { key: "success", label: "نتیجه", type: "slot", align: "center" },
  { key: "reason_fa", label: "علت" },
  { key: "ip_address", label: "IP" },
  { key: "user_agent", label: "مرورگر" },
];
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="امنیت" description="سیاست رمز، قفل حساب، نشست‌ها، قواعد IP و توکن‌های API">
      <template #actions>
        <div class="flex bg-surface rounded-xl shadow-soft p-1 overflow-x-auto">
          <button
            v-for="t in ([
              ['overview', 'نمای کلی'], ['sessions', 'نشست‌ها'], ['ip', 'قواعد IP'],
              ['tokens', 'توکن‌های API'], ['logins', 'تاریخچه ورود'],
            ] as const)"
            :key="t[0]"
            class="px-3 py-1.5 text-sm rounded-lg transition whitespace-nowrap"
            :class="tab === t[0] ? 'bg-panel text-white' : 'text-slate-500 hover:bg-slate-100'"
            @click="tab = t[0]"
          >{{ t[1] }}</button>
        </div>
      </template>
    </PageHeader>

    <div v-if="loading" class="text-center text-slate-400 py-16 text-sm">در حال بارگذاری…</div>

    <!-- ============ Overview ============ -->
    <template v-else-if="tab === 'overview' && overview">
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          label="نشست‌های فعال" :value="faNum(overview.active_sessions)" icon="activity" tone="brand"
        />
        <StatCard
          label="حساب‌های قفل‌شده" :value="faNum(overview.locked_users.length)" icon="lock"
          :tone="overview.locked_users.length ? 'bad' : 'good'"
        />
        <StatCard
          label="ورود ناموفق ۲۴ ساعت" :value="faNum(overview.failed_24h)" icon="alert"
          :tone="overview.failed_24h ? 'warn' : 'good'"
          :hint="`${faNum(overview.failed_7d)} در ۷ روز`"
        />
        <StatCard
          label="توکن‌های فعال" :value="faNum(overview.tokens.active)" icon="key"
          :hint="overview.tokens.expired ? `${faNum(overview.tokens.expired)} منقضی` : ''"
        />
      </div>

      <div class="grid lg:grid-cols-2 gap-4">
        <!-- Policy -->
        <section class="bg-surface rounded-card shadow-soft p-4">
          <h2 class="font-semibold text-ink mb-3">سیاست رمز عبور و قفل حساب</h2>
          <div v-if="policy" class="space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <label class="block">
                <span class="text-xs text-slate-500">حداقل طول رمز</span>
                <input
                  v-model.number="policy.min_length" type="number" min="4" max="64"
                  :disabled="!canManage()"
                  class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums disabled:opacity-60"
                />
              </label>
              <label class="block">
                <span class="text-xs text-slate-500">انقضای رمز (روز، ۰ = هرگز)</span>
                <input
                  v-model.number="policy.expiry_days" type="number" min="0"
                  :disabled="!canManage()"
                  class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums disabled:opacity-60"
                />
              </label>
              <label class="block">
                <span class="text-xs text-slate-500">تلاش ناموفق تا قفل (۰ = بدون قفل)</span>
                <input
                  v-model.number="policy.max_failed_attempts" type="number" min="0"
                  :disabled="!canManage()"
                  class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums disabled:opacity-60"
                />
              </label>
              <label class="block">
                <span class="text-xs text-slate-500">مدت قفل (دقیقه)</span>
                <input
                  v-model.number="policy.lockout_minutes" type="number" min="1"
                  :disabled="!canManage()"
                  class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums disabled:opacity-60"
                />
              </label>
            </div>

            <div class="space-y-2 pt-1">
              <Toggle v-model="policy.require_uppercase" label="الزام حرف بزرگ" :disabled="!canManage()" />
              <Toggle v-model="policy.require_lowercase" label="الزام حرف کوچک" :disabled="!canManage()" />
              <Toggle v-model="policy.require_digit" label="الزام رقم" :disabled="!canManage()" />
              <Toggle v-model="policy.require_symbol" label="الزام نویسه ویژه" :disabled="!canManage()" />
              <Toggle
                v-model="policy.enforce_ip_rules"
                label="اعمال قواعد IP"
                hint="تا وقتی خاموش است، قواعد فهرست IP فقط ثبت می‌شوند و اثری ندارند."
                :disabled="!canManage()"
              />
            </div>

            <div v-if="canManage()" class="flex justify-end pt-1">
              <button
                class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
                :disabled="savingPolicy"
                @click="savePolicy"
              >{{ savingPolicy ? "در حال ذخیره…" : "ذخیره سیاست" }}</button>
            </div>
          </div>
        </section>

        <div class="space-y-4">
          <!-- Locked accounts -->
          <section class="bg-surface rounded-card shadow-soft p-4">
            <h2 class="font-semibold text-ink mb-3">حساب‌های قفل‌شده</h2>
            <p v-if="!overview.locked_users.length" class="text-sm text-slate-400">
              هیچ حسابی قفل نیست.
            </p>
            <ul v-else class="space-y-2">
              <li
                v-for="u in overview.locked_users" :key="u.id"
                class="flex items-center justify-between gap-2 text-sm"
              >
                <div class="min-w-0">
                  <p class="text-ink truncate">{{ u.name }}</p>
                  <p class="text-[11px] text-slate-400 truncate">
                    {{ u.is_locked ? (u.reason || "قفل دستی") : `تا ${faDateTime(u.locked_until)}` }}
                  </p>
                </div>
                <button
                  v-if="admin.can('users.lock')"
                  class="text-xs text-accent-600 hover:underline shrink-0"
                  @click="unlock(u.id)"
                >باز کردن</button>
              </li>
            </ul>
          </section>

          <!-- 2FA -->
          <section class="bg-surface rounded-card shadow-soft p-4">
            <h2 class="font-semibold text-ink mb-1">ورود دومرحله‌ای (2FA)</h2>
            <p class="text-xs text-amber-600 bg-amber-50 rounded-xl px-3 py-2 mb-3">
              وضعیت 2FA در این پنل مدیریت می‌شود، اما اعتبارسنجی آن هنگام ورود هنوز فعال نشده است.
            </p>
            <dl class="space-y-1.5 text-sm">
              <div class="flex justify-between">
                <dt class="text-slate-500">کاربران با 2FA فعال</dt>
                <dd class="text-ink ltr-nums">{{ faNum(overview.twofa_enabled) }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-slate-500">ملزم به تغییر رمز</dt>
                <dd class="text-ink ltr-nums">{{ faNum(overview.must_change_password) }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-slate-500">قواعد IP</dt>
                <dd>
                  <Badge :tone="overview.ip_rules.enforced ? 'good' : 'neutral'">
                    {{ overview.ip_rules.enforced ? "اعمال می‌شود" : "غیرفعال" }} ·
                    {{ faNum(overview.ip_rules.allow) }} مجاز / {{ faNum(overview.ip_rules.deny) }} مسدود
                  </Badge>
                </dd>
              </div>
            </dl>
          </section>
        </div>
      </div>
    </template>

    <!-- ============ Sessions ============ -->
    <DataTable
      v-else-if="tab === 'sessions'"
      :columns="sessionColumns"
      :rows="sessions"
      empty-title="کسی در حال حاضر آنلاین نیست"
      empty-hint="نشست‌ها بر اساس ضربان حضور کاربران (هر ۳۰ ثانیه) شناسایی می‌شوند."
      @refresh="loadSessions"
    >
      <template #toolbar>
        <button
          v-if="admin.can('security.sessions')"
          class="text-xs px-2.5 py-1.5 rounded-lg bg-red-500 text-white hover:bg-red-600"
          @click="endAllSessions"
        >خروج اجباری همه</button>
      </template>
      <template #cell-since="{ row }">
        <span class="text-xs text-slate-500">{{ row.since ? timeAgo(row.since) : "—" }}</span>
      </template>
      <template #cell-last_seen="{ row }">
        <Badge tone="good" dot>{{ timeAgo(row.last_seen) }}</Badge>
      </template>
      <template #actions="{ row }">
        <button
          v-if="admin.can('security.sessions')"
          class="text-xs text-red-500 hover:underline"
          @click="endSession(row)"
        >پایان نشست</button>
      </template>
    </DataTable>

    <!-- ============ IP rules ============ -->
    <DataTable
      v-else-if="tab === 'ip'"
      :columns="ipColumns"
      :rows="ipRules"
      exportable
      empty-title="قاعده‌ای ثبت نشده است"
      empty-hint="اگر حتی یک قاعده «مجاز» فعال باشد، فهرست تبدیل به whitelist می‌شود."
      @refresh="loadIpRules"
      @export="(f) => securityApi.ipRules.export(f)"
    >
      <template #toolbar>
        <button
          v-if="canManage()"
          class="text-xs px-2.5 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700"
          @click="ipOpen = true"
        >+ قاعده جدید</button>
      </template>
      <template #cell-mode="{ row }">
        <Badge :tone="row.mode === 'allow' ? 'good' : 'bad'">
          {{ row.mode === "allow" ? "مجاز" : "مسدود" }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <button
          v-if="canManage()"
          class="text-xs text-red-500 hover:underline"
          @click="removeIpRule(row)"
        >حذف</button>
      </template>
    </DataTable>

    <!-- ============ Tokens ============ -->
    <DataTable
      v-else-if="tab === 'tokens'"
      :columns="tokenColumns"
      :rows="tokens"
      empty-title="توکنی ساخته نشده است"
      empty-hint="توکن‌ها برای اتصال سامانه‌های دیگر به API استفاده می‌شوند."
      @refresh="loadTokens"
    >
      <template #toolbar>
        <button
          v-if="admin.can('security.tokens')"
          class="text-xs px-2.5 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700"
          @click="tokenOpen = true"
        >+ توکن جدید</button>
      </template>
      <template #cell-is_active="{ row }">
        <Badge v-if="row.is_expired" tone="warn" dot>منقضی</Badge>
        <Badge v-else :tone="row.is_active ? 'good' : 'neutral'" dot>
          {{ row.is_active ? "فعال" : "باطل" }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <button
          v-if="row.is_active && admin.can('security.tokens')"
          class="text-xs text-red-500 hover:underline"
          @click="revokeToken(row)"
        >ابطال</button>
      </template>
    </DataTable>

    <!-- ============ Logins ============ -->
    <DataTable
      v-else
      :columns="loginColumns"
      :rows="logins"
      :client="false"
      :total="loginTotal"
      :page-size="25"
      exportable
      dense
      search-placeholder="نام کاربری، IP، مرورگر…"
      empty-title="ورودی ثبت نشده است"
      @query="(q) => loadLogins(q)"
      @refresh="loadLogins()"
      @export="(f) => loginEventsApi.export(f)"
    >
      <template #cell-success="{ row }">
        <Badge :tone="row.success ? 'good' : 'bad'" dot>
          {{ row.success ? "موفق" : "ناموفق" }}
        </Badge>
      </template>
    </DataTable>

    <!-- ============ IP rule drawer ============ -->
    <Drawer :open="ipOpen" title="قاعده IP جدید" width="sm" @close="ipOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نوع</span>
          <select v-model="ipForm.mode" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option value="deny">مسدود (blacklist)</option>
            <option value="allow">مجاز (whitelist)</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">آدرس یا محدوده *</span>
          <input
            v-model="ipForm.cidr" placeholder="192.168.1.10 یا 10.0.0.0/8"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums"
          />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">توضیح</span>
          <input v-model="ipForm.note" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <Toggle v-model="ipForm.is_active" label="قاعده فعال است" />
        <p class="text-xs text-amber-600 bg-amber-50 rounded-xl px-3 py-2">
          یادآوری: قواعد فقط زمانی اعمال می‌شوند که «اعمال قواعد IP» در سیاست امنیتی روشن باشد.
        </p>
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="ipOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="!ipForm.cidr"
          @click="saveIpRule"
        >ثبت</button>
      </template>
    </Drawer>

    <!-- ============ Token drawer ============ -->
    <Drawer :open="tokenOpen" title="توکن API جدید" width="sm" @close="tokenOpen = false">
      <div class="space-y-3">
        <label class="block">
          <span class="text-xs text-slate-500">نام توکن *</span>
          <input v-model="tokenForm.name" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface" />
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">به نام کاربر *</span>
          <select v-model="tokenForm.user" class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface">
            <option value="">انتخاب کنید…</option>
            <option v-for="u in users" :key="u.id" :value="u.id">{{ u.name }}</option>
          </select>
        </label>
        <label class="block">
          <span class="text-xs text-slate-500">تاریخ انقضا (اختیاری)</span>
          <input
            v-model="tokenForm.expires_at" type="date"
            class="mt-1 w-full border border-slate-200 rounded-xl px-3 py-2 text-sm bg-surface ltr-nums"
          />
        </label>
      </div>
      <template #footer>
        <button class="px-4 py-2 text-sm rounded-xl hover:bg-slate-100" @click="tokenOpen = false">انصراف</button>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50"
          :disabled="!tokenForm.name || !tokenForm.user"
          @click="createToken"
        >ساخت توکن</button>
      </template>
    </Drawer>

    <!-- ============ Issued token ============ -->
    <Drawer
      :open="!!issuedToken"
      title="توکن ساخته شد"
      subtitle="این مقدار فقط همین یک بار نمایش داده می‌شود"
      width="sm"
      @close="issuedToken = null"
    >
      <code class="block bg-slate-100 rounded-xl p-3 text-xs ltr-nums break-all select-all">
        {{ issuedToken }}
      </code>
      <p class="text-xs text-slate-400 mt-2">
        سرور فقط هش این توکن را نگه می‌دارد؛ اگر گمش کنید باید توکن تازه بسازید.
      </p>
      <template #footer>
        <button
          class="px-4 py-2 text-sm rounded-xl bg-brand-600 text-white hover:bg-brand-700"
          @click="issuedToken = null"
        >ذخیره‌اش کردم</button>
      </template>
    </Drawer>
  </div>
</template>
