<script setup lang="ts">
import { computed } from "vue";
import type { QueryResult, WidgetOptions } from "@/api/dashboards";
import { byUnit } from "./format";

/**
 * The same query result, read as rows.
 *
 * A split query returns its columns keyed by the split's *labels* rather than
 * by metric keys (there is only one metric in that shape), so the header is
 * taken from whichever the result actually has instead of from the config —
 * one table component for both shapes, and no way for the two to disagree.
 */
const props = withDefaults(defineProps<{
  result: QueryResult;
  options?: WidgetOptions;
}>(), { options: () => ({}) });

const split = computed(() => !!props.result.split);

const columns = computed(() => {
  if (split.value) {
    return props.result.series.map((s) => ({ key: s.name, label: s.name, unit: s.unit }));
  }
  return props.result.series.map((s) => ({ key: s.key, label: s.name, unit: s.unit }));
});

const emit = defineEmits<{ (e: "drill", key: string, label: string): void }>();

const showTotals = computed(
  () => !split.value && props.options.showValues !== false && props.result.rows.length > 1,
);
</script>

<template>
  <div class="h-full overflow-auto -mx-1">
    <table class="w-full text-xs">
      <thead class="sticky top-0 bg-surface">
        <tr class="text-slate-400">
          <th class="text-right font-medium py-1.5 px-2 whitespace-nowrap">
            {{ result.dimension?.label ?? "" }}
          </th>
          <th
            v-for="c in columns" :key="c.key"
            class="text-left font-medium py-1.5 px-2 whitespace-nowrap"
          >{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in result.rows" :key="row.key"
          class="border-t border-slate-100 hover:bg-slate-50/60 transition-colors cursor-pointer"
          @click="emit('drill', row.key, row.label)"
        >
          <td class="py-1.5 px-2 text-ink whitespace-nowrap max-w-[180px] truncate" :title="row.label">
            {{ row.label }}
          </td>
          <td
            v-for="c in columns" :key="c.key"
            class="py-1.5 px-2 text-left ltr-nums text-slate-600 whitespace-nowrap"
          >{{ byUnit(row.values[c.key] ?? 0, c.unit) }}</td>
        </tr>
      </tbody>
      <tfoot v-if="showTotals">
        <tr class="border-t-2 border-slate-200 font-semibold">
          <td class="py-1.5 px-2 text-ink">مجموع</td>
          <td
            v-for="c in columns" :key="c.key"
            class="py-1.5 px-2 text-left ltr-nums text-ink whitespace-nowrap"
          >{{ byUnit(result.totals[c.key] ?? 0, c.unit) }}</td>
        </tr>
      </tfoot>
    </table>
    <p v-if="!result.rows.length" class="text-xs text-slate-400 text-center py-6">
      ردیفی برای این بازه ثبت نشده است.
    </p>
  </div>
</template>
