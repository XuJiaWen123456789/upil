<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  createConversation,
  deleteConversation,
  getConversationMessages,
  listConversations,
  renameConversation,
} from "@/api/conversations";
import { withDemoIdentity } from "@/api/identity";
import { consumePostSse } from "@/api/sse";
import ConversationRenameDialog from "@/components/chat/ConversationRenameDialog.vue";
import ConversationSidebar from "@/components/chat/ConversationSidebar.vue";
import type { ConversationSummary, LeadChatCard } from "@/types/api";
import { formatApiDateTime } from "@/utils/datetime";

interface ChatEventData {
  stage?: string;
  content?: string;
  report_task_id?: string;
  navigation_path?: string;
  navigation_label?: string;
}

interface ChatAction {
  path: "/parent/reports";
  label: string;
}

interface ChatMessage {
  kind: "user" | "assistant";
  content: string;
  meta: string;
  lead?: LeadChatCard;
  action?: ChatAction;
  /** 联系方式只在当前请求发送期间短暂存在，完成后立即从页面内存擦除。 */
  sensitive?: boolean;
}

const router = useRouter();
const question = ref("");
const conversationId = ref<string | null>(null);
const conversations = ref<ConversationSummary[]>([]);
const messages = ref<ChatMessage[]>([]);
const status = ref("正在加载会话");
const loading = ref(false);
const historyLoading = ref(true);
const historyError = ref("");
const controller = ref<AbortController | null>(null);
const messagesElement = ref<HTMLElement | null>(null);
const renameTarget = ref<ConversationSummary | null>(null);
const renameSaving = ref(false);

// 导航动作来自后端固定业务契约，前端再次做白名单校验，避免任意模型输出、
// 用户输入或错误接口数据被当成外链、管理端路径或脚本地址执行。
const allowedNavigationPaths = new Set(["/parent/reports"]);
const quickQuestions = ["查询孩子最近的出勤和课时", "如何办理课程请假？", "我想预约舞蹈试听课"];

function scrollToBottom() {
  void nextTick(() => {
    if (messagesElement.value) messagesElement.value.scrollTop = messagesElement.value.scrollHeight;
  });
}

function looksLikeContactSubmission(text: string): boolean {
  // 这里只判断是否需要隐藏页面原文；格式校验、授权判断和加密入库仍由后端负责。
  const normalized = text.replace(/[\s-]/g, "");
  return /(?:手机号|手机|电话|联系方式|邮箱|email|e-mail)/i.test(text)
    || /1\d{8,14}/.test(normalized)
    || /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(text);
}

function clearSensitiveMessage(message: ChatMessage) {
  if (!message.sensitive) return;
  message.content = "已提交联系方式（原文已隐藏）";
}

function historyMeta(role: "user" | "assistant", createdAt: string): string {
  const time = formatApiDateTime(createdAt, {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
  return role === "user" ? "您 · " + time : "uPil 学习顾问 · " + time;
}

async function refreshConversationList(): Promise<ConversationSummary[]> {
  const response = await listConversations();
  conversations.value = response.items;
  return response.items;
}

async function openConversation(id: string) {
  if (loading.value || (historyLoading.value && conversationId.value === id)) return;
  controller.value?.abort();
  historyLoading.value = true;
  historyError.value = "";
  try {
    const history = await getConversationMessages(id);
    // 只有读取成功后才切换当前 ID，越权或已删除会话不会污染当前页面状态。
    conversationId.value = id;
    messages.value = history.items.map((item) => ({
      kind: item.role,
      content: item.content,
      meta: historyMeta(item.role, item.created_at),
    }));
    status.value = "就绪";
    scrollToBottom();
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : "无法读取会话历史";
    status.value = "历史加载失败";
  } finally {
    historyLoading.value = false;
  }
}

async function newConversation() {
  if (loading.value || historyLoading.value) return;
  controller.value?.abort();
  historyLoading.value = true;
  historyError.value = "";
  try {
    const created = await createConversation();
    conversationId.value = created.conversation_id;
    messages.value = [];
    status.value = "就绪";
    await refreshConversationList();
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : "新建会话失败";
    status.value = "新建失败";
  } finally {
    historyLoading.value = false;
  }
}

async function initializeConversations() {
  historyLoading.value = true;
  historyError.value = "";
  try {
    const items = await refreshConversationList();
    if (items.length) {
      const first = items[0];
      const history = await getConversationMessages(first.conversation_id);
      conversationId.value = first.conversation_id;
      messages.value = history.items.map((item) => ({
        kind: item.role,
        content: item.content,
        meta: historyMeta(item.role, item.created_at),
      }));
    } else {
      const created = await createConversation();
      conversationId.value = created.conversation_id;
      conversations.value = [created];
      messages.value = [];
    }
    status.value = "就绪";
    scrollToBottom();
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : "会话服务暂时不可用";
    status.value = "会话服务异常";
  } finally {
    historyLoading.value = false;
  }
}

async function saveRename(title: string) {
  if (!renameTarget.value || renameSaving.value) return;
  renameSaving.value = true;
  historyError.value = "";
  try {
    await renameConversation(renameTarget.value.conversation_id, title);
    renameTarget.value = null;
    await refreshConversationList();
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : "重命名失败";
  } finally {
    renameSaving.value = false;
  }
}

async function removeConversation(target: ConversationSummary) {
  if (loading.value || historyLoading.value) return;
  // 删除不可撤销，因此先要求用户确认；确认框不展示任何消息正文。
  if (!window.confirm("确认删除会话“" + target.title + "”吗？")) return;
  historyLoading.value = true;
  historyError.value = "";
  try {
    await deleteConversation(target.conversation_id);
    const remaining = await refreshConversationList();
    if (target.conversation_id !== conversationId.value) return;
    if (remaining.length) {
      const next = remaining[0];
      const history = await getConversationMessages(next.conversation_id);
      conversationId.value = next.conversation_id;
      messages.value = history.items.map((item) => ({
        kind: item.role,
        content: item.content,
        meta: historyMeta(item.role, item.created_at),
      }));
    } else {
      const created = await createConversation();
      conversationId.value = created.conversation_id;
      conversations.value = [created];
      messages.value = [];
    }
    status.value = "就绪";
    scrollToBottom();
  } catch (cause) {
    historyError.value = cause instanceof Error ? cause.message : "删除会话失败";
  } finally {
    historyLoading.value = false;
  }
}

async function send() {
  const text = question.value.trim();
  if (!text || loading.value || historyLoading.value || !conversationId.value) return;
  controller.value?.abort();
  controller.value = new AbortController();
  loading.value = true;
  status.value = "处理中";
  const userMessage: ChatMessage = { kind: "user", content: text, meta: "您", sensitive: looksLikeContactSubmission(text) };
  messages.value.push(userMessage);
  scrollToBottom();
  question.value = "";
  const assistant: ChatMessage = { kind: "assistant", content: "", meta: "uPil 学习顾问 · 流式生成中" };
  messages.value.push(assistant);
  scrollToBottom();
  const started = performance.now();
  try {
    const response = await fetch(withDemoIdentity("/api/v1/chat/stream"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message: text, conversation_id: conversationId.value }),
      signal: controller.value.signal,
    });
    let complete = false;
    await consumePostSse(response, ({ event, data }) => {
      const payload = (data || {}) as ChatEventData;
      if (event === "token") {
        assistant.content += payload.content || "";
        scrollToBottom();
      }
      if (event === "lead") {
        // 卡片完全采用后端安全投影，不展示证据码、内部队列或联系方式明文。
        assistant.lead = payload as LeadChatCard;
        scrollToBottom();
      }
      if (event === "complete") {
        complete = true;
        assistant.meta = "uPil 学习顾问 · 已回复 · " + Math.round(performance.now() - started) + " ms";
        status.value = "已完成";
        if (payload.navigation_path && allowedNavigationPaths.has(payload.navigation_path)) {
          assistant.action = { path: "/parent/reports", label: payload.navigation_label || "查看学情报告" };
        }
        if (payload.report_task_id) void router.push("/parent/reports/" + encodeURIComponent(payload.report_task_id));
      }
    });
    if (!complete) throw new Error("连接已结束，但未收到 complete 完成事件");
  } catch (cause) {
    if ((cause as Error).name === "AbortError") status.value = "已取消";
    else {
      status.value = "请求异常";
      assistant.content = cause instanceof Error ? cause.message : "网络连接失败，请稍后重试。";
      assistant.meta = "连接错误";
    }
  } finally {
    clearSensitiveMessage(userMessage);
    loading.value = false;
    controller.value = null;
    // 回答完成后刷新目录，显示服务端生成的标题和最新活动时间。
    try {
      await refreshConversationList();
    } catch {
      historyError.value = "回答已完成，但会话目录刷新失败。";
    }
  }
}

onMounted(() => { void initializeConversations(); });
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">CONVERSATION CENTER</span><h1>对话中心</h1><p>把课程咨询、服务规则和学情入口放在同一个安全工作台。</p></div>
  </div>
  <div v-if="historyError" class="alert conversation-alert">{{ historyError }}</div>
  <div class="chat-workspace">
    <ConversationSidebar
      :items="conversations"
      :current-id="conversationId"
      :loading="historyLoading"
      :disabled="loading"
      @create="newConversation"
      @select="openConversation"
      @rename="renameTarget = $event"
      @remove="removeConversation"
    />
    <div class="chat-layout">
      <section class="panel chat-panel">
        <div ref="messagesElement" class="chat-messages">
          <div v-if="historyLoading" class="welcome-message"><strong>正在读取会话…</strong></div>
          <div v-else-if="!messages.length" class="welcome-message"><strong>你好，我是 uPil 学习顾问。</strong><p>可以询问课程、请假、课时，也可以进入孩子的学情报告。</p></div>
          <div v-for="(message, index) in messages" :key="index" class="message" :class="message.kind">
            <div class="bubble">{{ message.content }}</div>
            <button v-if="message.action" type="button" class="button secondary chat-action" @click="router.push(message.action.path)">{{ message.action.label }}</button>
            <section v-if="message.lead" class="lead-chat-card" aria-label="试听与报名意向">
              <div class="lead-chat-head"><strong>{{ message.lead.course_name }}</strong></div>
              <p>{{ message.lead.prompt }}</p>
              <small v-if="message.lead.contact_masked">已授权联系方式：{{ message.lead.contact_masked }}</small>
            </section>
            <span class="message-meta">{{ message.meta }}</span>
          </div>
        </div>
        <form class="chat-compose" @submit.prevent="send">
          <textarea v-model="question" placeholder="输入你的问题，Ctrl/⌘ + Enter 发送" :disabled="loading || historyLoading || !conversationId" @keydown.ctrl.enter.prevent="send" @keydown.meta.enter.prevent="send" />
          <button class="button primary" type="submit" :disabled="loading || historyLoading || !conversationId || !question.trim()">{{ loading ? "生成中" : "发送" }}</button>
        </form>
      </section>
      <aside class="stack chat-tools">
        <section class="panel panel-pad"><span class="eyebrow">QUICK START</span><h3>快捷提问</h3><div class="stack"><button v-for="item in quickQuestions" :key="item" class="button secondary" :disabled="loading || historyLoading" @click="question = item">{{ item }}</button></div></section>
        <section class="panel panel-pad"><div class="metric-label">服务状态</div><strong class="metric-value" style="font-size:20px">{{ status }}</strong><p class="metric-note">对话内容会按照当前身份执行权限校验。</p></section>
      </aside>
    </div>
  </div>
  <ConversationRenameDialog
    :open="renameTarget !== null"
    :initial-title="renameTarget?.title || ''"
    :saving="renameSaving"
    @close="renameTarget = null"
    @save="saveRename"
  />
</template>
