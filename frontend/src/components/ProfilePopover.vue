<script setup lang="ts">
import { useRouter } from "vue-router";
import type { TeamMember } from "@/api/social";
import UserAvatar from "@/components/UserAvatar.vue";

const props = defineProps<{ member: TeamMember }>();
const emit = defineEmits<{ (e: "close"): void }>();
const router = useRouter();

function openChat() {
  router.push({ name: "chat", query: { with: String(props.member.id) } });
  emit("close");
}
function openProfile() {
  router.push({ name: "profile", params: { id: String(props.member.id) } });
  emit("close");
}
function call() {
  if (props.member.phone) window.location.href = `tel:${props.member.phone}`;
}
</script>

<template>
  <!-- Dark rounded card, exactly like the mockup's hover popover -->
  <div class="bg-panel text-white rounded-card shadow-pop p-3 w-64 animate-pop">
    <div class="flex items-center gap-3 mb-3">
      <UserAvatar
        :name="member.name"
        :initials="member.initials"
        :color="member.avatar_color"
        :online="member.is_online"
        :size="44"
      />
      <div class="min-w-0">
        <p class="font-semibold truncate">{{ member.name }}</p>
        <p class="text-xs text-white/60 truncate">{{ member.job_title_fa || member.department_label }}</p>
      </div>
    </div>

    <div class="flex items-center justify-between gap-2">
      <button
        class="flex-1 h-10 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center transition"
        title="پروفایل"
        @click="openProfile"
      >👤</button>
      <button
        class="flex-1 h-10 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center transition"
        title="گفتگو"
        @click="openChat"
      >💬</button>
      <button
        class="flex-1 h-10 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center transition disabled:opacity-40"
        title="تماس"
        :disabled="!member.phone"
        @click="call"
      >📞</button>
    </div>
  </div>
</template>
