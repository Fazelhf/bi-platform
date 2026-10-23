<script setup lang="ts">
/**
 * یک نامه، تمام‌صفحه.
 *
 * Where a notification lands, and where a phone opens a letter — there is no
 * room for a reading pane beside the list on a small screen. Everything the
 * page does lives in LetterReader, which the mailbox's side pane uses too.
 */
import { computed } from "vue";
import { useRoute } from "vue-router";
import LetterReader from "@/components/office/LetterReader.vue";

const route = useRoute();
const id = computed(() => Number(route.params.id));
</script>

<template>
  <div class="office-card overflow-hidden max-w-4xl mx-auto" style="min-height: calc(100vh - 9rem)">
    <LetterReader :id="id" />
  </div>
</template>
