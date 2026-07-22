import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import router from "./router";
import { useUiStore } from "./stores/ui";
import "./style.css";

const app = createApp(App);
app.use(createPinia()).use(router);
// Load the CEO-selected chart theme before first paint.
useUiStore().fetch();
app.mount("#app");
