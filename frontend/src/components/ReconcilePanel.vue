<script setup lang="ts">
import type { Reconciliation } from "@/types";
import { num } from "@/utils/format";

/**
 * Shows that the weeks really do add up to the month.
 *
 * The two figures come from different code paths — each week's total is
 * computed from that week's own rows, the month's from all its leaves at once
 * — so this is a genuine check of the roll-up, not a restatement of it.
 */
defineProps<{ recon: Reconciliation | null }>();
</script>

<template>
  <div v-if="recon && recon.weeks.length" class="space-y-2">
    <div
      class="rounded-xl px-3 py-2 text-sm flex items-center justify-between gap-3 flex-wrap"
      :class="recon.balanced
        ? 'bg-accent-50 text-accent-600'
        : 'bg-red-50 text-red-600'"
    >
      <span class="font-medium">
        {{ recon.balanced ? "✓ جمع هفته‌ها با ماه برابر است" : "✗ مغایرت پیدا شد" }}
      </span>
      <span class="ltr-nums text-xs">
        جمع هفته‌ها {{ num(Number(recon.weeks_total)) }}
        =
        ماه {{ num(Number(recon.month_total)) }}
      </span>
    </div>

    <p
      v-if="recon.month_holds_own_figures"
      class="text-xs text-red-600 bg-red-50 rounded-xl px-3 py-2 leading-6"
    >
      روی خود ماه هم عدد ثبت شده و هم هفته‌هایش عدد دارند. این تنها حالتی است که
      باعث دوبار شمردن می‌شود — اطلاعات ماه باید پاک شود و فقط در هفته‌ها وارد شود.
    </p>

    <div v-if="!recon.balanced" class="text-xs text-slate-500 ltr-nums">
      اختلاف: {{ num(Number(recon.difference)) }}
    </div>

    <table class="w-full text-xs">
      <tbody>
        <tr v-for="w in recon.weeks" :key="w.seq" class="border-b border-slate-50">
          <td class="py-1 text-slate-500">هفته {{ w.seq }}</td>
          <td class="py-1 text-left ltr-nums">{{ num(Number(w.revenue)) }}</td>
        </tr>
        <tr class="font-semibold text-ink">
          <td class="py-1">جمع</td>
          <td class="py-1 text-left ltr-nums">{{ num(Number(recon.weeks_total)) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
