<script setup lang="ts">
import { computed } from "vue";
import type { ChartNode, Seat } from "@/api/hr";

/**
 * One section of a department: its seats and — recursively — its own
 * sub-sections, drawn nested inside it.
 */
const props = withDefaults(defineProps<{
  node: ChartNode;
  query?: string;
  nested?: boolean;
  color?: string;
}>(), { query: "", nested: false, color: "" });

const emit = defineEmits<{
  (e: "edit-unit", node: ChartNode): void;
  (e: "add-unit", parent: ChartNode): void;
  (e: "edit-seat", seat: Seat, node: ChartNode): void;
  (e: "add-seat", node: ChartNode): void;
}>();

const colour = computed(() => props.node.color || props.color || "#64748b");
const seats = computed(() => [
  ...props.node.positions.filter((p) => p.is_head),
  ...props.node.positions.filter((p) => !p.is_head),
]);

const q = computed(() => props.query.trim());
const hit = (seat: Seat) => !!q.value && `${seat.holder_name} ${seat.title}`.includes(q.value);
const initial = (name: string) => (name ? name.trim()[0] : "؟");
</script>

<template>
  <div
    :class="[
      nested ? 'mt-2 rounded-lg border border-slate-100 bg-slate-50/50' : 'bg-surface rounded-xl border border-slate-100 shadow-soft',
      !node.is_active ? 'opacity-50' : '',
    ]"
  >
    <header class="flex items-center gap-2 px-3 pt-2.5 pb-1.5">
      <span class="w-1.5 h-4 rounded-full shrink-0" :style="{ background: colour }" />
      <p class="text-[13px] font-bold truncate flex-1 min-w-0" :style="{ color: colour }">
        {{ node.name_fa }}
        <span v-if="!node.is_active" class="text-[10px] text-slate-400 font-normal">(غیرفعال)</span>
      </p>
      <span
        v-if="node.sales_channel"
        class="text-[10px] rounded-full px-1.5 py-0.5 bg-sky-50 text-sky-600 shrink-0"
        :title="`افراد این واحد در برگه ${node.sales_channel_label} هستند`"
      >{{ node.sales_channel_label }}</span>
      <div class="flex items-center shrink-0 text-slate-300">
        <button class="hover:text-ink px-1 text-xs" title="افزودن سمت" @click="emit('add-seat', node)">+</button>
        <button class="hover:text-ink px-1 text-xs" title="ویرایش واحد" @click="emit('edit-unit', node)">✎</button>
      </div>
    </header>

    <div class="px-2 pb-2">
      <button
        v-for="seat in seats" :key="seat.id"
        type="button"
        class="w-full flex items-center gap-2 px-1.5 py-1.5 text-right rounded-lg hover:bg-slate-100 transition-colors"
        :class="hit(seat) ? 'bg-amber-50 ring-2 ring-amber-200' : ''"
        @click="emit('edit-seat', seat, node)"
      >
        <span
          class="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0 border"
          :class="seat.holder ? '' : 'border-dashed border-amber-300 bg-amber-50 text-amber-600'"
          :style="seat.holder ? {
            color: colour,
            background: `color-mix(in srgb, ${colour} 12%, transparent)`,
            borderColor: `color-mix(in srgb, ${colour} 25%, transparent)`,
          } : {}"
        >{{ initial(seat.holder_name) }}</span>
        <span class="min-w-0 flex-1 leading-tight">
          <span
            class="block text-[13px] truncate"
            :class="seat.holder ? 'text-ink font-medium' : 'text-amber-600'"
          >{{ seat.holder_name || "نامشخص" }}</span>
          <span class="block text-[11px] text-slate-400 truncate">
            {{ seat.title }}<template v-if="seat.is_head"> · مسئول</template>
          </span>
        </span>
        <!-- Who can sign in, at a glance; «ساخت حساب» is on the people page. -->
        <span
          v-if="seat.holder"
          class="w-2 h-2 rounded-full shrink-0"
          :class="seat.holder_user ? 'bg-green-500' : 'bg-slate-300'"
          :title="seat.holder_user ? 'حساب کاربری دارد' : 'حساب کاربری ندارد'"
        />
      </button>

      <p v-if="!node.positions.length && !node.children.length" class="text-[11px] text-slate-300 py-2 text-center">
        سمتی تعریف نشده
      </p>

      <ChartUnit
        v-for="child in node.children" :key="child.id"
        :node="child" :query="query" nested :color="colour"
        @edit-unit="(n) => emit('edit-unit', n)"
        @add-unit="(n) => emit('add-unit', n)"
        @edit-seat="(s, n) => emit('edit-seat', s, n)"
        @add-seat="(n) => emit('add-seat', n)"
      />
      <button
        v-if="!nested"
        class="w-full text-[11px] text-slate-300 hover:text-ink pt-1"
        @click="emit('add-unit', node)"
      >+ زیرواحد</button>
    </div>
  </div>
</template>
