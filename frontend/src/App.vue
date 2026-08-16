<script setup lang="ts">
import UiHost from "@/components/UiHost.vue";
// Above the router view, not inside a shell: offline and «نسخه‌ی جدید» are
// true of the whole app, including the login page and the CRM and admin
// layouts, which have shells of their own.
import PwaBanner from "@/components/PwaBanner.vue";
</script>

<template>
  <router-view />
  <UiHost />
  <PwaBanner />
</template>
