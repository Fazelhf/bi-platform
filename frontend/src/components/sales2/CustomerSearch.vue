<script setup lang="ts">
import { ref, watch } from "vue";
import { sales2Api, type CustomerRow } from "@/api/sales2";

/**
 * انتخاب مشتری از پرونده‌ی CRM.
 *
 * CRM holds ~3,700 customers, too many to ship to a PickerField and filter in
 * the browser, so this asks the server as you type. The results open in the
 * flow of the page rather than floating, so a modal's scroll box cannot clip
 * them.
 */
const props = defineProps<{ modelValue: number | null; label?: string; disabled?: boolean }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: number | null): void;
  (e: "picked", c: CustomerRow | null): void;
}>();

const q = ref("");
const results = ref<CustomerRow[]>([]);
const open = ref(false);
const loading = ref(false);
const chosen = ref<string>(props.label ?? "");
let timer: ReturnType<typeof setTimeout> | undefined;

watch(() => props.label, (v) => { if (v) chosen.value = v; });

watch(q, (value) => {
  clearTimeout(timer);
  if (value.trim().length < 2) { results.value = []; return; }
  timer = setTimeout(async () => {
    loading.value = true;
    try {
      results.value = await sales2Api.customers({ q: value.trim(), light: 1 });
      open.value = true;
    } finally {
      loading.value = false;
    }
  }, 250);
});

function pick(c: CustomerRow) {
  chosen.value = c.name_fa;
  emit("update:modelValue", c.id);
  emit("picked", c);
  open.value = false;
  q.value = "";
}

function clear() {
  chosen.value = "";
  emit("update:modelValue", null);
  emit("picked", null);
}
</script>

<template>
  <div>
    <div
      v-if="modelValue && chosen"
      class="flex items-center justify-between gap-2 bg-slate-100 rounded-xl px-3 py-2 text-sm"
    >
      <span class="text-ink font-medium truncate">{{ chosen }}</span>
      <button v-if="!disabled" type="button" class="text-xs text-slate-400 hover:text-ink" @click="clear">تغییر</button>
    </div>
    <template v-else>
      <input
        v-model="q"
        :disabled="disabled"
        placeholder="نام، کد، شناسه ملی یا تلفن مشتری…"
        class="w-full bg-slate-100 rounded-xl px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-slate-300"
        @focus="open = results.length > 0"
      />
      <p v-if="loading" class="text-xs text-slate-400 mt-1">در حال جستجو…</p>
      <ul
        v-else-if="open && results.length"
        class="mt-1 border border-slate-100 rounded-xl divide-y divide-slate-100 max-h-64 overflow-y-auto bg-surface"
      >
        <li v-for="c in results" :key="c.id">
          <button
            type="button"
            class="w-full text-right px-3 py-2 hover:bg-slate-50"
            @click="pick(c)"
          >
            <span class="text-sm text-ink">{{ c.name_fa }}</span>
            <span class="block text-xs text-slate-400 ltr-nums">
              {{ [c.national_id, c.phone, c.city].filter(Boolean).join(" · ") }}
            </span>
          </button>
        </li>
      </ul>
      <p v-else-if="q.trim().length >= 2 && open" class="text-xs text-slate-400 mt-1">مشتری‌ای پیدا نشد.</p>
    </template>
  </div>
</template>
