<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { socialApi, type TeamMember } from "@/api/social";
import UserAvatar from "@/components/UserAvatar.vue";
import ProfilePopover from "@/components/ProfilePopover.vue";

const members = ref<TeamMember[]>([]);
const loading = ref(true);
const openId = ref<number | null>(null);
let timer: number | undefined;

async function load() {
  members.value = await socialApi.team();
  loading.value = false;
}

const onlineCount = () => members.value.filter((m) => m.is_online).length;

onMounted(() => {
  load();
  timer = window.setInterval(load, 30_000); // refresh presence
});
onBeforeUnmount(() => window.clearInterval(timer));
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-bold text-ink">اعضای تیم</h2>
      <span class="text-sm text-slate-400">
        <span class="text-accent-500 font-semibold ltr-nums">{{ onlineCount() }}</span> نفر آنلاین
      </span>
    </div>

    <div v-if="loading" class="text-slate-400">در حال بارگذاری…</div>

    <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
      <div
        v-for="m in members"
        :key="m.id"
        class="relative bg-white rounded-card shadow-soft p-5 flex flex-col items-center text-center hover:shadow-pop transition cursor-pointer"
        @click="openId = openId === m.id ? null : m.id"
      >
        <UserAvatar :name="m.name" :initials="m.initials" :color="m.avatar_color" :online="m.is_online" :size="64" />
        <p class="mt-3 font-semibold text-ink">{{ m.name }}</p>
        <p class="text-xs text-slate-400">{{ m.job_title_fa || m.department_label }}</p>
        <span
          class="mt-2 text-[11px] px-2 py-0.5 rounded-full"
          :class="m.is_online ? 'bg-accent-50 text-accent-600' : 'bg-slate-100 text-slate-400'"
        >{{ m.is_online ? "آنلاین" : "آفلاین" }}</span>

        <!-- Popover -->
        <div v-if="openId === m.id" class="absolute z-30 top-full mt-2" @click.stop>
          <ProfilePopover :member="m" @close="openId = null" />
        </div>
      </div>
    </div>
  </div>
</template>
