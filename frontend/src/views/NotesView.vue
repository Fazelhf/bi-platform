<script setup lang="ts">
import { ref } from "vue";
import { socialApi, type Note } from "@/api/social";

const notes = ref<Note[]>([]);
const loading = ref(true);
const adding = ref(false);
const form = ref({ title: "", body: "" });

async function load() {
  loading.value = true;
  try {
    notes.value = (await socialApi.notes()).filter((n) => n.subject === null);
  } catch {
    notes.value = [];
  } finally {
    loading.value = false;
  }
}
load();
async function save() {
  if (!form.value.body.trim() && !form.value.title.trim()) return;
  await socialApi.createNote({ title: form.value.title, body: form.value.body, subject: null });
  form.value = { title: "", body: "" };
  adding.value = false;
  await load();
}
async function remove(id: number) {
  if (confirm("این یادداشت حذف شود؟")) {
    await socialApi.deleteNote(id);
    await load();
  }
}
function fmt(iso: string) {
  return new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium" }).format(new Date(iso));
}
</script>

<template>
  <div class="max-w-2xl">
    <!-- Dark card, like the mockup's یادداشت‌ها -->
    <div class="bg-ink text-white rounded-card shadow-soft p-5">
      <div class="flex items-center justify-between mb-4">
        <h2 class="font-bold">یادداشت‌ها</h2>
        <button
          class="w-9 h-9 rounded-xl bg-accent-500 hover:bg-accent-600 flex items-center justify-center text-lg"
          @click="adding = !adding"
        >{{ adding ? "×" : "+" }}</button>
      </div>

      <!-- Add form -->
      <div v-if="adding" class="bg-white/5 rounded-2xl p-3 mb-4 space-y-2 animate-pop">
        <input
          v-model="form.title"
          placeholder="عنوان"
          class="w-full bg-white/10 rounded-lg px-3 py-2 text-sm outline-none placeholder-white/40"
        />
        <textarea
          v-model="form.body"
          rows="3"
          placeholder="متن یادداشت…"
          class="w-full bg-white/10 rounded-lg px-3 py-2 text-sm outline-none placeholder-white/40"
        ></textarea>
        <div class="flex justify-end">
          <button class="bg-accent-500 hover:bg-accent-600 rounded-lg px-4 py-1.5 text-sm" @click="save">ذخیره</button>
        </div>
      </div>

      <!-- Loading: shimmering note placeholders -->
      <div v-if="loading" class="space-y-2">
        <div v-for="i in 3" :key="i" class="bg-white/5 rounded-2xl p-3">
          <div class="skeleton skeleton-dark h-3.5 w-1/3 mb-2"></div>
          <div class="skeleton skeleton-dark h-3 w-2/3"></div>
        </div>
      </div>
      <div v-else-if="!notes.length" class="text-center py-8">
        <div class="text-3xl mb-2 select-none">📝</div>
        <p class="text-white/70 text-sm">یادداشتی ثبت نشده است.</p>
        <p class="text-white/40 text-xs mt-1">با دکمه + اولین یادداشت را اضافه کنید.</p>
      </div>

      <div class="space-y-2">
        <div
          v-for="n in notes"
          :key="n.id"
          class="bg-white/5 hover:bg-white/10 rounded-2xl p-3 flex items-start gap-3 transition group"
        >
          <div class="flex-1 min-w-0">
            <p class="font-medium">{{ n.title || "بدون عنوان" }}</p>
            <p v-if="n.body" class="text-sm text-white/60 mt-1 whitespace-pre-wrap">{{ n.body }}</p>
            <p class="text-xs text-white/40 mt-2 ltr-nums">{{ fmt(n.created_at) }}</p>
          </div>
          <button
            class="text-white/30 hover:text-red-400 opacity-0 group-hover:opacity-100 transition"
            @click="remove(n.id)"
          >🗑</button>
        </div>
      </div>
    </div>
  </div>
</template>
