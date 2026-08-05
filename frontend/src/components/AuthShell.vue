<script setup lang="ts">
/**
 * The signed-out chrome: brand panel on one side, a narrow column on the
 * other. Shared by every way into the platform (password, کد پیامکی,
 * فراموشی رمز) so the three screens stay one screen with three forms.
 */
import ThemePicker from "@/components/ThemePicker.vue";

defineProps<{ title: string; subtitle: string }>();

const YEAR = new Date().toLocaleDateString("fa-IR", { year: "numeric" });
</script>

<template>
  <div class="min-h-screen grid lg:grid-cols-[1.05fr_1fr] bg-canvas">
    <!-- ================= Brand panel (desktop only) ================= -->
    <!-- First in DOM, so in RTL it sits on the right. -->
    <aside class="relative hidden lg:flex flex-col justify-between overflow-hidden bg-panel p-12 text-white">
      <!-- soft depth: two blurred colour pools + a faint grid -->
      <div class="pointer-events-none absolute -top-32 -right-24 w-96 h-96 rounded-full bg-brand-500/25 blur-3xl"></div>
      <div class="pointer-events-none absolute -bottom-40 -left-24 w-[28rem] h-[28rem] rounded-full bg-accent-500/15 blur-3xl"></div>
      <div
        class="pointer-events-none absolute inset-0 opacity-[0.04]"
        style="background-image:linear-gradient(currentColor 1px,transparent 1px),linear-gradient(90deg,currentColor 1px,transparent 1px);background-size:44px 44px"
      ></div>

      <div class="relative flex items-center gap-3">
        <img src="/apple-touch-icon.png" alt="" class="w-11 h-11 rounded-xl shadow-soft" />
        <span class="font-bold text-lg">کاغذ حساس نمابر مهر</span>
      </div>

      <div class="relative">
        <h2 class="text-3xl font-extrabold leading-[1.7]">
          سامانه هوش تجاری
        </h2>
        <p class="text-white/60 mt-3 leading-8 max-w-md">
          فروش، تولید و شاخص‌های کلیدی سازمان — یک‌جا، به‌روز و قابل اتکا برای تصمیم‌گیری.
        </p>

        <div class="flex flex-wrap gap-2 mt-8">
          <span
            v-for="t in ['فروش همکار', 'فروش بانکی', 'فروش B2B', 'تولید']"
            :key="t"
            class="text-xs bg-white/10 rounded-full px-3 py-1.5"
          >{{ t }}</span>
        </div>
      </div>

      <p class="relative text-xs text-white/35 ltr-nums">© {{ YEAR }} — نمابر مهر</p>
    </aside>

    <!-- ===================== Form column ===================== -->
    <main class="flex items-center justify-center p-6 sm:p-10">
      <div class="w-full max-w-sm space-y-6 animate-pop">
        <!-- Compact brand mark, mobile only (the panel covers desktop) -->
        <div class="flex flex-col items-center gap-3 lg:hidden">
          <img src="/apple-touch-icon.png" alt="" class="w-16 h-16 rounded-2xl shadow-soft" />
          <h1 class="text-lg font-bold text-ink text-center">شرکت کاغذ حساس نمابر مهر</h1>
        </div>

        <div class="hidden lg:block">
          <h1 class="text-2xl font-bold text-ink">{{ title }}</h1>
          <p class="text-sm text-slate-400 mt-1.5 leading-7">{{ subtitle }}</p>
        </div>

        <slot />

        <div class="flex items-center justify-between pt-1 gap-3">
          <div class="text-xs text-slate-400 leading-6">
            <slot name="footer">مشکلی در ورود دارید؟ با مدیر سیستم تماس بگیرید.</slot>
          </div>
          <!-- Skin and light/dark are both inside the palette, so there is no
               separate sun/moon button here either. -->
          <ThemePicker />
        </div>
      </div>
    </main>
  </div>
</template>
