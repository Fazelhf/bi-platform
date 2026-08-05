import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { useUiStore } from "./stores/ui";
import "./style.css";

const app = createApp(App);
app.use(createPinia()).use(router);

const ui = useUiStore();
// Apply the saved skin and light/dark choice before the first paint, so the
// page never flashes the wrong theme on reload.
ui.initAppearance();
// Load the CEO-selected chart theme before first paint.
ui.fetch();

app.mount("#app");
