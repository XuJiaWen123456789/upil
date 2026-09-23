import { createRouter, createWebHistory } from "vue-router";
import { useSessionStore } from "@/stores/session";
import type { Capability, Role } from "@/types/api";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/chat" },
    { path: "/chat", component: () => import("@/views/ChatView.vue"), meta: { capability: "chat_access", feature: "chat" } },
    { path: "/parent/learning", component: () => import("@/views/ParentLearningView.vue"), meta: { capability: "learning_read", role: "parent", feature: "parent_learning" } },
    { path: "/parent/reports", component: () => import("@/views/ReportsView.vue"), meta: { capability: "report_read", role: "parent", feature: "parent_reports" } },
    { path: "/parent/reports/:taskId", component: () => import("@/views/ReportDetailView.vue"), meta: { capability: "report_read", role: "parent", feature: "parent_reports" } },
    { path: "/teacher/classes", component: () => import("@/views/ClassLearningView.vue"), meta: { capability: "class_summary_read", role: "teacher", feature: "teacher_class_summary" } },
    { path: "/teacher/reports/:taskId", component: () => import("@/views/ReportDetailView.vue"), meta: { capability: "class_summary_read", role: "teacher", feature: "teacher_class_summary" } },
    { path: "/teacher/leads", component: () => import("@/views/LeadWorkspaceView.vue"), meta: { capability: "lead_followup", role: "teacher", feature: "teacher_lead_workspace" } },
    { path: "/:pathMatch(.*)*", component: () => import("@/views/NotFoundView.vue") },
  ],
});

router.beforeEach(async (to) => {
  const store = useSessionStore();
  // 直接打开深层链接时，App.vue 的 onMounted 可能尚未完成会话初始化。
  // 在守卫中等待会话加载，避免已授权用户先被错误重定向到聊天页。
  if (store.loading && !store.session) await store.initialize();
  if (!store.session) return "/chat";
  const expectedRole = to.meta.role as Role | undefined;
  const capability = to.meta.capability as Capability | undefined;
  const feature = to.meta.feature as string | undefined;
  if (expectedRole && store.role !== expectedRole) return "/chat";
  if (capability && !store.has(capability)) return "/chat";
  if (feature && !store.featureEnabled(feature)) return "/chat";
  return true;
});
