<script setup lang="ts">
import { computed } from "vue";
import { useMoney } from "@/composables/useMoney";
import { num } from "@/utils/format";
import { faDate } from "@/utils/adminFormat";
import EmptyState from "@/components/EmptyState.vue";

/**
 * The records behind a figure.
 *
 * It renders the rows the card arrived with — it never fetches. What is
 * listed is by construction exactly what was counted, so the panel cannot
 * show a total that disagrees with the tile it opened from, which is the
 * usual failure of drill-downs that re-query with hand-copied filters.
 *
 * Columns travel with the data, so one panel serves every card without
 * knowing anything about files, containers or invoices.
 */
export interface DrillColumn {
  key: string;
  label: string;
  type?: "text" | "number" | "money" | "date";
  align?: "left" | "right";
}

const props = defineProps<{
  title: string;
  subtitle?: string;
  columns: DrillColumn[];
  rows: Record<string, any>[];
  /** Foreign-currency figures are not Rial and must not be scaled. */
  currency?: string;
}>();
const emit = defineEmits<{ (e: "close"): void; (e: "pick", row: any): void }>();

const { exact } = useMoney();
const FA = new Intl.NumberFormat("fa-IR");

const isRial = computed(() => !props.currency);

function cell(row: Record<string, any>, col: DrillColumn): string {
  const v = row[col.key];
  if (v === null || v === undefined || v === "") return "—";
  if (col.type === "money") {
    return isRial.value ? exact(v) : FA.format(Number(v));
  }
  if (col.type === "number") return num(v);
  if (col.type === "date") return faDate(v);
  return String(v);
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-[70] bg-black/30 flex justify-start"
      dir="rtl"
      @click.self="emit('close')"
    >
      <div class="bg-surface h-full w-full max-w-3xl flex flex-col shadow-pop">
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div class="min-w-0">
            <h2 class="font-bold text-ink">{{ title }}</h2>
            <p class="text-xs text-slate-400 mt-0.5">
              <span class="ltr-nums">{{ num(rows.length) }}</span> ردیف
              <span v-if="subtitle"> · {{ subtitle }}</span>
            </p>
          </div>
          <button
            class="text-slate-400 hover:text-ink text-2xl leading-none px-1"
            @click="emit('close')"
          >×</button>
        </header>

        <div class="flex-1 overflow-auto">
          <EmptyState v-if="!rows.length" title="ردیفی پشت این عدد نیست" />
          <table v-else class="w-full text-sm">
            <thead class="sticky top-0 bg-slate-50">
              <tr class="text-xs text-slate-400">
                <th
                  v-for="c in columns" :key="c.key"
                  class="font-medium px-4 py-2.5"
                  :class="c.align === 'left' ? 'text-left' : 'text-right'"
                >{{ c.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(r, i) in rows" :key="r.id ?? i"
                class="border-t border-slate-100 hover:bg-slate-50"
                :class="r.id ? 'cursor-pointer' : ''"
                @click="r.id && emit('pick', r)"
              >
                <td
                  v-for="c in columns" :key="c.key"
                  class="px-4 py-2.5"
                  :class="[
                    c.align === 'left' ? 'text-left' : 'text-right',
                    c.type === 'money' || c.type === 'number' || c.type === 'date'
                      ? 'ltr-nums' : '',
                    c.key === columns[0].key ? 'text-ink font-medium' : 'text-slate-500',
                  ]"
                >{{ cell(r, c) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </Teleport>
</template>
