<script setup lang="ts">
import { ref } from "vue";

/**
 * Shared shell for every CRM entry form: header, scrollable body, sticky
 * footer, and one place that renders server-side validation errors. Each form
 * only supplies its fields.
 */
withDefaults(defineProps<{
  title: string;
  subtitle?: string;
  saving?: boolean;
  error?: string;
  wide?: boolean;
  saveLabel?: string;
  canDelete?: boolean;
}>(), { saving: false, error: "", wide: false, saveLabel: "ذخیره", canDelete: false });

const emit = defineEmits<{
  (e: "close"): void;
  (e: "save"): void;
  (e: "delete"): void;
}>();

const confirmDelete = ref(false);
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[65] bg-black/40 flex items-start justify-center p-3 sm:p-6 overflow-y-auto" dir="rtl">
      <div
        class="bg-surface rounded-card shadow-pop w-full my-auto flex flex-col max-h-[92vh]"
        :class="wide ? 'max-w-3xl' : 'max-w-lg'"
      >
        <header class="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3 shrink-0">
          <div class="min-w-0">
            <h2 class="font-bold text-ink">{{ title }}</h2>
            <p v-if="subtitle" class="text-xs text-slate-400 mt-0.5 truncate">{{ subtitle }}</p>
          </div>
          <button class="text-slate-400 hover:text-ink text-2xl leading-none px-1" @click="emit('close')">×</button>
        </header>

        <div class="flex-1 overflow-y-auto p-5 space-y-4">
          <p v-if="error" class="bg-red-50 text-red-600 text-sm rounded-xl px-3 py-2 whitespace-pre-line">{{ error }}</p>
          <slot />
        </div>

        <footer class="px-5 py-3 border-t border-slate-100 flex items-center gap-2 shrink-0">
          <button
            class="bg-panel text-white rounded-xl px-5 py-2 text-sm disabled:opacity-50"
            :disabled="saving"
            @click="emit('save')"
          >{{ saving ? "در حال ذخیره…" : saveLabel }}</button>
          <button class="px-4 py-2 text-sm text-slate-500 hover:bg-slate-100 rounded-xl" @click="emit('close')">
            انصراف
          </button>

          <span class="flex-1"></span>

          <template v-if="canDelete">
            <button
              v-if="!confirmDelete"
              class="text-sm text-red-500 hover:bg-red-50 rounded-xl px-3 py-2"
              @click="confirmDelete = true"
            >حذف</button>
            <template v-else>
              <span class="text-xs text-slate-500">مطمئنید؟</span>
              <button class="text-sm bg-red-500 text-white rounded-xl px-3 py-2" @click="emit('delete')">بله، حذف کن</button>
              <button class="text-sm text-slate-500 px-2" @click="confirmDelete = false">نه</button>
            </template>
          </template>
        </footer>
      </div>
    </div>
  </Teleport>
</template>
