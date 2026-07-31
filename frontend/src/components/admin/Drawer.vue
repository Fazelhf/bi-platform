<script setup lang="ts">
/** Side sheet for create/edit forms and detail views. Esc closes it. */
import { onMounted, onUnmounted } from "vue";
import NavIcon from "@/components/NavIcon.vue";

const props = withDefaults(defineProps<{
  open: boolean;
  title: string;
  subtitle?: string;
  width?: "sm" | "md" | "lg";
  busy?: boolean;
}>(), { width: "md" });

const emit = defineEmits<{ (e: "close"): void }>();

const WIDTHS = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl" };

function onKey(event: KeyboardEvent) {
  if (event.key === "Escape" && props.open) emit("close");
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[60] flex" dir="rtl">
      <div class="absolute inset-0 bg-black/40" @click="emit('close')"></div>
      <aside
        class="relative mr-auto h-full w-full bg-surface shadow-pop flex flex-col animate-pop"
        :class="WIDTHS[width]"
      >
        <header class="flex items-start gap-3 p-4 border-b border-slate-100 shrink-0">
          <div class="flex-1 min-w-0">
            <h2 class="font-bold text-ink truncate">{{ title }}</h2>
            <p v-if="subtitle" class="text-xs text-slate-400 mt-0.5 truncate">{{ subtitle }}</p>
          </div>
          <button
            class="text-slate-400 hover:text-ink p-1 rounded-lg hover:bg-slate-100"
            aria-label="بستن"
            @click="emit('close')"
          ><NavIcon name="close" :size="18" /></button>
        </header>

        <div class="flex-1 overflow-y-auto p-4">
          <slot />
        </div>

        <footer
          v-if="$slots.footer"
          class="p-4 border-t border-slate-100 flex items-center justify-end gap-2 shrink-0"
          :class="{ 'opacity-60 pointer-events-none': busy }"
        >
          <slot name="footer" />
        </footer>
      </aside>
    </div>
  </Teleport>
</template>
