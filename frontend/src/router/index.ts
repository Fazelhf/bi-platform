import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: () => import("@/views/LoginView.vue") },
    {
      path: "/",
      component: () => import("@/components/AppLayout.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", redirect: "/dashboard" },
        { path: "dashboard", name: "dashboard", component: () => import("@/views/DashboardView.vue") },
        { path: "entry", name: "entry", component: () => import("@/views/DataEntryView.vue") },
      ],
    },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthenticated) return { name: "login" };
  if (to.name === "login" && auth.isAuthenticated) return { name: "dashboard" };
});

export default router;
