import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { getBootstrap, getSession } from "@/api/client";
import { clearDemoIdentity, setDemoIdentity } from "@/api/identity";
import type { Capability, FrontendBootstrap, Role, SessionInfo } from "@/types/api";

/** 全局会话状态只保存界面需要的最小信息，不保存 Bearer Token。 */
export const useSessionStore = defineStore("session", () => {
  const bootstrap = ref<FrontendBootstrap | null>(null);
  const session = ref<SessionInfo | null>(null);
  const loading = ref(true);
  const error = ref("");

  const isDemo = computed(() => bootstrap.value?.demo_mode === true);
  const role = computed<Role | null>(() => session.value?.role ?? null);
  const capabilities = computed(() => new Set(session.value?.capabilities ?? []));
  let initializePromise: Promise<void> | null = null;

  function initialize(): Promise<void> {
    if (bootstrap.value && session.value) return Promise.resolve();
    // App 与路由守卫可能在首屏同时触发初始化。缓存进行中的 Promise，
    // 确保公开 bootstrap 和鉴权 session 各只请求一次，避免竞态覆盖状态。
    if (initializePromise) return initializePromise;
    initializePromise = initializeOnce().finally(() => {
      initializePromise = null;
    });
    return initializePromise;
  }

  async function initializeOnce(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      bootstrap.value = await getBootstrap();
      const saved = isDemo.value ? readDemoIdentity() : null;
      if (saved) setDemoIdentity(saved.role, saved.userId);
      // 身份参数由 API 客户端统一从当前 Demo 身份追加，避免这里再次拼接
      // actor_role/actor_user_id 造成重复查询参数，也让业务请求走同一条边界。
      session.value = await getSession();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "无法初始化工作台";
    } finally {
      loading.value = false;
    }
  }

  async function switchDemoRole(nextRole: Role, userId: string) {
    if (!isDemo.value) return;
    sessionStorage.setItem("upil.demo.identity", JSON.stringify({ role: nextRole, userId }));
    setDemoIdentity(nextRole, userId);
    try {
      // setDemoIdentity 已经更新请求上下文，会话请求不再接收第二份身份参数。
      session.value = await getSession();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "切换身份失败";
    }
  }

  function resetDemoIdentity() {
    sessionStorage.removeItem("upil.demo.identity");
    clearDemoIdentity();
  }

  function has(capability: Capability): boolean {
    return capabilities.value.has(capability);
  }

  function featureEnabled(feature: string): boolean {
    return bootstrap.value?.features[feature] === true;
  }

  function readDemoIdentity(): { role: string; userId: string } | null {
    try {
      const raw = sessionStorage.getItem("upil.demo.identity");
      if (!raw) return null;
      const value = JSON.parse(raw) as { role?: unknown; userId?: unknown };
      return typeof value.role === "string" && typeof value.userId === "string"
        ? { role: value.role, userId: value.userId }
        : null;
    } catch {
      return null;
    }
  }

  return { bootstrap, session, loading, error, isDemo, role, capabilities, initialize, switchDemoRole, resetDemoIdentity, has, featureEnabled };
});
