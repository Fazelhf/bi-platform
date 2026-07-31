<script setup lang="ts">
import { timeAgo } from "@/utils/adminFormat";
import type { TimelineItem } from "@/types/admin";

defineProps<{ items: TimelineItem[]; empty?: string }>();

const TONE: Record<string, string> = {
  create: "bg-accent-500", update: "bg-brand-600", delete: "bg-red-500",
  approve: "bg-accent-500", reject: "bg-red-500", revision: "bg-amber-500",
  submit: "bg-sky-500", import: "bg-violet-500", formula: "bg-violet-500",
  login: "bg-accent-500", login_failed: "bg-red-500",
};
</script>

<template>
  <div v-if="!items.length" class="text-sm text-slate-400 py-8 text-center">
    {{ empty || "رویدادی ثبت نشده است." }}
  </div>
  <ol v-else class="relative pr-4">
    <!-- The spine sits on the right, matching RTL reading order. -->
    <span class="absolute top-1 bottom-1 right-[3px] w-px bg-slate-200"></span>
    <li v-for="(item, i) in items" :key="i" class="relative pb-4 last:pb-0">
      <span
        class="absolute right-0 top-1.5 w-[7px] h-[7px] rounded-full ring-2 ring-surface"
        :class="TONE[item.action] || 'bg-slate-400'"
      ></span>
      <div class="pr-4">
        <p class="text-sm text-ink leading-snug">{{ item.text }}</p>
        <p class="text-[11px] text-slate-400 mt-0.5">
          {{ item.actor }} · {{ timeAgo(item.at) }}
        </p>
      </div>
    </li>
  </ol>
</template>
