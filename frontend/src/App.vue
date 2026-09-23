<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";
import { demoIdentityGroups, findDemoIdentity } from "@/config/demoIdentities";
import { useSessionStore } from "@/stores/session";

const sessionStore = useSessionStore();
const router = useRouter();

const roleLabels: Record<string, string> = { parent: "家长", teacher: "教师" };
const currentDemoIdentity = computed(() =>
  findDemoIdentity(sessionStore.session?.demo_user_id),
);
const identityLabel = computed(() => {
  // 本地切换模式优先显示数据库业务账号；生产认证不返回 demo_user_id，
  // 因而仍按服务端能力画像显示通用角色名称。
  if (currentDemoIdentity.value) return currentDemoIdentity.value.label;
  // 销售顾问是 teacher 下的最小权限业务画像，不能依赖演示账号 ID 判断，
  // 否则切换到生产认证后会错误显示为普通教师。
  if (sessionStore.has("lead_followup")) return "销售顾问老师";
  return roleLabels[sessionStore.role || ""] || "未识别";
});
const workspaceIdentityKey = computed(() =>
  sessionStore.session?.demo_user_id || sessionStore.role || "anonymous",
);

onMounted(() => {
  void sessionStore.initialize();
});

async function selectIdentity(event: Event) {
  const target = event.target as HTMLSelectElement;
  const identity = findDemoIdentity(target.value);
  if (!identity) return;
  await sessionStore.switchDemoRole(identity.role, identity.userId);
  // 身份切换后立即离开原角色页面，不能继续展示已经挂载的旧角色视图。
  await router.push("/chat");
}
</script>

<template>
  <div v-if="sessionStore.loading" class="boot-screen">
    <div class="boot-card"><span class="eyebrow">uPil WORKSPACE</span><h1>正在加载安全工作台</h1><p>正在读取公开启动配置和当前会话能力。</p></div>
  </div>
  <div v-else-if="sessionStore.error" class="boot-screen">
    <div class="boot-card error-card"><span class="eyebrow">无法连接</span><h1>工作台暂时不可用</h1><p>{{ sessionStore.error }}</p><button class="button primary" @click="sessionStore.initialize">重新连接</button></div>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">u</span><div><strong>uPil</strong><small>学习成长工作台</small></div></div>
      <div class="role-card">
        <span class="label">当前身份</span>
        <strong>{{ identityLabel }}</strong>
        <span class="connection-dot"><i /> 已连接</span>
        <label v-if="sessionStore.isDemo" class="demo-switcher">
          切换身份
          <select :value="sessionStore.session?.demo_user_id || ''" @change="selectIdentity">
            <optgroup
              v-for="group in demoIdentityGroups"
              :key="group.key"
              :label="group.label"
            >
              <option
                v-for="identity in group.identities"
                :key="identity.userId"
                :value="identity.userId"
              >
                {{ identity.label }}
              </option>
            </optgroup>
          </select>
        </label>
      </div>
      <nav class="nav-list" aria-label="主导航">
        <RouterLink v-if="sessionStore.featureEnabled('chat') && sessionStore.has('chat_access')" to="/chat" class="nav-link"><span>◈</span>对话中心</RouterLink>
        <template v-if="sessionStore.role === 'parent'">
          <RouterLink v-if="sessionStore.featureEnabled('parent_learning') && sessionStore.has('learning_read')" to="/parent/learning" class="nav-link"><span>◌</span>孩子学情</RouterLink>
          <RouterLink v-if="sessionStore.featureEnabled('parent_reports') && sessionStore.has('report_read')" to="/parent/reports" class="nav-link"><span>▤</span>学情报告</RouterLink>
        </template>
        <template v-if="sessionStore.role === 'teacher'">
          <RouterLink v-if="sessionStore.featureEnabled('teacher_class_summary') && sessionStore.has('class_summary_read')" to="/teacher/classes" class="nav-link"><span>▥</span>班级统计</RouterLink>
          <RouterLink v-if="sessionStore.featureEnabled('teacher_lead_workspace') && sessionStore.has('lead_followup')" to="/teacher/leads" class="nav-link"><span>◎</span>销售线索</RouterLink>
        </template>
      </nav>
      <div class="sidebar-foot"><span class="eyebrow">PRIVACY</span><p>学员信息仅向经过授权的家长和教师展示，请勿转发包含个人信息的页面或文件。</p></div>
    </aside>
    <main class="main-area">
      <header class="topbar"><div><span class="eyebrow">LEARNING SERVICE</span><h2>{{ sessionStore.bootstrap?.app_name || 'uPil 工作台' }}</h2></div><div class="topbar-note">家校学习服务</div></header>
      <!-- 身份变化时强制重新挂载业务页面，防止旧身份的聊天、报告或线索状态残留。 -->
      <section class="content-area"><RouterView :key="workspaceIdentityKey" /></section>
    </main>
  </div>
</template>
