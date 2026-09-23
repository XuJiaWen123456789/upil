import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "@/App.vue";
import { router } from "@/router";
import "@/styles.css";
import "@/leads.css";
import "@/reports.css";

const app = createApp(App);
// 先安装 Pinia，再让 router 守卫读取会话状态；App 负责显示首屏加载态，
// 路由守卫仍会在用户直接打开深层链接时等待同一会话初始化过程。
app.use(createPinia());
app.use(router);
app.mount("#app");
