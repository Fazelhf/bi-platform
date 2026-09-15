<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { rosterApi, type RosterMember, type Team } from "@/api/sales";
import { useAuthStore } from "@/stores/auth";
import { toast, confirm } from "@/composables/useUi";
import { num, rial } from "@/utils/format";
import Skeleton from "@/components/Skeleton.vue";
import EmptyState from "@/components/EmptyState.vue";

/**
 * «تیم فروش / تیم من» — who is on a channel's entry sheet.
 *
 * The list itself is no longer edited here. It is read from منابع انسانی:
 * whoever holds a seat in this channel's unit on the chart is on it, and
 * whoever is moved out or archived drops off. Managers kept the list by hand
 * before, which is how people went missing and duplicates crept in.
 *
 * What stays the manager's is the regional grouping (ایران غرب، تهران، …),
 * which is a sales matter rather than who works in the company.
 */
const auth = useAuthStore();

const CHANNELS = [
  { key: "team", label: "فروش همکار", dept: "sales_team" },
  { key: "organizational", label: "فروش بانکی", dept: "sales_org" },
  { key: "psp", label: "فروش PSP", dept: "sales_org" },
  { key: "b2b", label: "فروش B2B", dept: "sales_b2b" },
];

/** A manager sees their own channels; the CEO picks. */
const visibleChannels = computed(() =>
  auth.isExecutive ? CHANNELS : CHANNELS.filter((c) => c.dept === auth.department),
);

const channel = ref(visibleChannels.value[0]?.key ?? "team");
const members = ref<RosterMember[]>([]);
const teams = ref<Team[]>([]);
const loading = ref(true);
const showInactive = ref(false);

async function load() {
  loading.value = true;
  try {
    members.value = await rosterApi.list(channel.value);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  teams.value = await rosterApi.teams();
  await load();
});
watch(channel, load);

const shown = computed(() =>
  showInactive.value ? members.value : members.value.filter((m) => m.is_active),
);
const inactiveCount = computed(() => members.value.filter((m) => !m.is_active).length);

const totals = computed(() => ({
  active: members.value.filter((m) => m.is_active).length,
  withLogin: members.value.filter((m) => m.is_active && m.has_login).length,
  revenue: members.value.reduce((s, m) => s + Number(m.total_revenue || 0), 0),
  neverEntered: members.value.filter((m) => m.is_active && !m.periods_filled).length,
}));

async function setTeam(m: RosterMember, teamId: string) {
  await rosterApi.update(m.id, { team: teamId ? Number(teamId) : null });
  await load();
}

/* ---- the regional teams ------------------------------------------------- */
const showTeams = ref(false);
const newTeamName = ref("");
const teamEditId = ref<number | null>(null);
const teamEditName = ref("");

async function reloadTeams() {
  teams.value = await rosterApi.teams();
}

async function addTeam() {
  const name = newTeamName.value.trim();
  if (!name) return;
  try {
    await rosterApi.addTeam(name);
    newTeamName.value = "";
    await reloadTeams();
    toast.success("تیم اضافه شد.");
  } catch {
    toast.error("اضافه نشد.");
  }
}

async function saveTeamName(t: Team) {
  const name = teamEditName.value.trim();
  teamEditId.value = null;
  if (!name || name === t.name_fa) return;
  try {
    await rosterApi.renameTeam(t.id, name);
    await Promise.all([reloadTeams(), load()]);
    toast.success("نام تیم ویرایش شد.");
  } catch {
    toast.error("ویرایش نشد.");
  }
}

async function deleteTeam(t: Team) {
  if (t.member_count) {
    toast.error(`«${t.name_fa}» ${t.member_count} عضو دارد؛ اول اعضا را به تیم دیگری منتقل کنید.`);
    return;
  }
  const ok = await confirm({ title: "حذف تیم", message: `تیم «${t.name_fa}» حذف شود؟`, danger: true });
  if (!ok) return;
  try {
    await rosterApi.deleteTeam(t.id);
    await reloadTeams();
    toast.success("تیم حذف شد.");
  } catch {
    toast.error("حذف نشد.");
  }
}

const card = "bg-surface rounded-card shadow-soft";
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-lg font-bold text-ink">{{ auth.isExecutive ? "تیم فروش" : "تیم من" }}</h2>
        <p class="text-xs text-slate-400 mt-0.5">
          کارشناسان هر بخش از چارت سازمانی خوانده می‌شوند و برگه‌های ورود اطلاعات از همین فهرست ساخته می‌شوند.
        </p>
      </div>
      <div class="flex items-center gap-2 flex-wrap">
        <select
          v-if="visibleChannels.length > 1"
          v-model="channel"
          class="bg-surface border border-slate-200 rounded-xl px-3 py-1.5 text-sm"
        >
          <option v-for="c in visibleChannels" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
        <button
          class="border border-slate-200 rounded-xl px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
          @click="showTeams = !showTeams"
        >مدیریت تیم‌های منطقه‌ای</button>
        <router-link
          v-if="auth.isExecutive"
          :to="{ name: 'hr-chart' }"
          class="bg-panel text-white rounded-xl px-4 py-2 text-sm"
        >ویرایش در منابع انسانی</router-link>
      </div>
    </div>

    <p class="bg-sky-50 text-sky-700 text-sm rounded-xl px-3 py-2">
      افزودن، جابه‌جایی یا خروج کارشناس در «منابع انسانی» انجام می‌شود
      <template v-if="!auth.isExecutive">— اگر کسی کم یا زیاد است، به مدیریت اطلاع دهید</template>.
      کسی که از شرکت رفته بایگانی می‌شود و آمار دوره‌های گذشته‌اش دست‌نخورده می‌ماند.
    </p>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div :class="card" class="p-4">
        <p class="text-xs text-slate-400">کارشناس فعال</p>
        <p class="text-xl font-bold text-ink mt-1 ltr-nums">{{ num(totals.active) }}</p>
      </div>
      <div :class="card" class="p-4">
        <p class="text-xs text-slate-400">دارای حساب کاربری</p>
        <p class="text-xl font-bold mt-1 ltr-nums" :class="totals.withLogin < totals.active ? 'text-amber-600' : 'text-ink'">
          {{ num(totals.withLogin) }} از {{ num(totals.active) }}
        </p>
      </div>
      <div :class="card" class="p-4">
        <p class="text-xs text-slate-400">فروش ثبت‌شده (کل دوره‌ها)</p>
        <p class="text-xl font-bold text-ink mt-1 ltr-nums">{{ rial(totals.revenue) }}</p>
      </div>
      <div :class="card" class="p-4">
        <p class="text-xs text-slate-400">بدون هیچ ثبتی</p>
        <p class="text-xl font-bold mt-1 ltr-nums" :class="totals.neverEntered ? 'text-red-500' : 'text-ink'">
          {{ num(totals.neverEntered) }}
        </p>
      </div>
    </div>

    <div v-if="showTeams" :class="card" class="p-5 space-y-3">
      <div class="flex items-center justify-between">
        <h3 class="font-bold text-ink text-sm">تیم‌های منطقه‌ای</h3>
        <button class="text-slate-400 hover:text-ink text-xl leading-none" @click="showTeams = false">×</button>
      </div>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="t in teams" :key="t.id"
          class="flex items-center gap-2 border border-slate-200 rounded-xl px-3 py-1.5"
        >
          <input
            v-if="teamEditId === t.id"
            v-model="teamEditName"
            class="bg-slate-50 rounded-lg px-2 py-1 text-sm w-32 outline-none"
            @keyup.enter="saveTeamName(t)"
            @blur="saveTeamName(t)"
          />
          <button v-else class="text-sm text-ink hover:underline"
                  @click="teamEditId = t.id; teamEditName = t.name_fa">
            {{ t.name_fa }}
          </button>
          <span class="text-[11px] text-slate-400">{{ num(t.member_count) }} عضو</span>
          <button
            class="text-slate-300 hover:text-red-500 text-sm leading-none"
            :title="t.member_count ? 'تیم دارای عضو حذف نمی‌شود' : 'حذف تیم'"
            @click="deleteTeam(t)"
          >×</button>
        </div>
      </div>
      <div class="flex items-center gap-2 border-t border-slate-100 pt-3">
        <input
          v-model="newTeamName" placeholder="نام تیم جدید — مثلاً ایران غرب"
          class="bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-sm flex-1 min-w-[180px] outline-none focus:ring-2 focus:ring-accent-500/30"
          @keyup.enter="addTeam"
        />
        <button
          class="bg-accent-500 hover:bg-accent-600 text-white rounded-xl px-4 py-2 text-sm disabled:opacity-50"
          :disabled="!newTeamName.trim()" @click="addTeam"
        >افزودن تیم</button>
      </div>
    </div>

    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 6" :key="i" class="h-12 rounded-xl" />
    </div>

    <EmptyState
      v-else-if="!shown.length"
      icon="👥"
      title="هنوز کارشناسی در این بخش نیست"
      hint="در منابع انسانی، کارشناسان را در واحد این بخش روی چارت قرار دهید."
    />

    <div v-else :class="card" class="overflow-hidden">
      <ul class="md:hidden divide-y divide-slate-100">
        <li
          v-for="m in shown" :key="`m-${m.id}`"
          class="p-4" :class="m.is_active ? '' : 'bg-slate-50/60 text-slate-400'"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="font-medium min-w-0 truncate" :class="m.is_active ? 'text-ink' : ''">{{ m.employee_name }}</span>
            <span v-if="!m.is_active" class="text-[11px] bg-slate-200 text-slate-500 rounded-full px-2 py-0.5 shrink-0">خارج از بخش</span>
          </div>
          <div class="flex items-center gap-2 mt-2 flex-wrap">
            <select
              :value="m.team ?? ''"
              class="bg-slate-50 border border-slate-200 rounded-lg px-2 py-1.5 text-sm outline-none"
              @change="setTeam(m, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">— بدون تیم</option>
              <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.name_fa }}</option>
            </select>
            <span v-if="m.has_login" class="text-xs text-green-600 ltr-nums">✓ {{ m.username }}</span>
            <span v-else class="text-xs text-amber-600">✗ بدون حساب</span>
          </div>
          <div class="flex items-center justify-between gap-2 mt-2 text-xs ltr-nums">
            <span :class="m.periods_filled ? 'text-slate-400' : 'text-red-500'">
              {{ num(m.periods_filled) }} دوره · {{ m.last_period || "—" }}
            </span>
            <span class="text-ink font-medium">{{ rial(Number(m.total_revenue)) }}</span>
          </div>
        </li>
      </ul>

      <div class="hidden md:block overflow-x-auto">
        <table class="w-full text-sm min-w-[700px]">
          <thead>
            <tr class="text-xs text-slate-400 bg-slate-50">
              <th class="text-right font-medium px-4 py-3">کارشناس</th>
              <th class="text-right font-medium px-3">تیم منطقه‌ای</th>
              <th class="text-right font-medium px-3">حساب کاربری</th>
              <th class="text-left font-medium px-3">دوره‌های ثبت‌شده</th>
              <th class="text-left font-medium px-3">آخرین ثبت</th>
              <th class="text-left font-medium px-4">فروش کل</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="m in shown" :key="m.id"
              class="border-t border-slate-100"
              :class="m.is_active ? 'hover:bg-slate-50' : 'bg-slate-50/60 text-slate-400'"
            >
              <td class="px-4 py-2.5">
                <span class="font-medium" :class="m.is_active ? 'text-ink' : ''">{{ m.employee_name }}</span>
                <span v-if="!m.is_active" class="text-[11px] bg-slate-200 text-slate-500 rounded-full px-2 py-0.5 mr-2">خارج از بخش</span>
              </td>
              <td class="px-3">
                <select
                  :value="m.team ?? ''"
                  class="bg-transparent border border-transparent hover:border-slate-200 rounded-lg px-2 py-1 text-sm outline-none"
                  @change="setTeam(m, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">—</option>
                  <option v-for="t in teams" :key="t.id" :value="t.id">{{ t.name_fa }}</option>
                </select>
              </td>
              <td class="px-3">
                <span v-if="m.has_login" class="text-xs text-green-600">✓ {{ m.username }}</span>
                <span v-else class="text-xs text-amber-600">✗ ندارد</span>
              </td>
              <td class="px-3 text-left ltr-nums">
                <span :class="m.periods_filled ? '' : 'text-red-500'">{{ num(m.periods_filled) }}</span>
              </td>
              <td class="px-3 text-left text-xs whitespace-nowrap">{{ m.last_period || "—" }}</td>
              <td class="px-4 text-left ltr-nums whitespace-nowrap">{{ rial(Number(m.total_revenue)) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="inactiveCount" class="px-4 py-2.5 border-t border-slate-100">
        <button class="text-xs text-slate-400 hover:text-ink" @click="showInactive = !showInactive">
          {{ showInactive ? "پنهان کردن" : "نمایش" }} {{ num(inactiveCount) }} نفر که دیگر در این بخش نیستند
        </button>
      </div>
    </div>
  </div>
</template>
