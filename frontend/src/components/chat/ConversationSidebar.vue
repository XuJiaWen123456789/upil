<script setup lang="ts">
import type { ConversationSummary } from "@/types/api";
import { formatApiDateTime } from "@/utils/datetime";

defineProps<{
  items: ConversationSummary[];
  currentId: string | null;
  loading: boolean;
  disabled: boolean;
}>();

const emit = defineEmits<{
  create: [];
  select: [conversationId: string];
  rename: [conversation: ConversationSummary];
  remove: [conversation: ConversationSummary];
}>();

function displayTime(value: string | null): string {
  if (!value) return "刚刚创建";
  return formatApiDateTime(value, {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
</script>

<template>
  <aside class="panel conversation-sidebar" aria-label="会话历史">
    <header class="conversation-sidebar-head">
      <div><span class="eyebrow">HISTORY</span><strong>会话历史</strong></div>
      <button class="button primary compact" type="button" :disabled="disabled" @click="emit('create')">+ 新建</button>
    </header>
    <div v-if="loading" class="conversation-empty">正在加载会话…</div>
    <div v-else-if="!items.length" class="conversation-empty">还没有历史会话</div>
    <ul v-else class="conversation-list">
      <li v-for="item in items" :key="item.conversation_id">
        <button
          type="button"
          class="conversation-item"
          :class="{ active: item.conversation_id === currentId }"
          :disabled="disabled"
          @click="emit('select', item.conversation_id)"
        >
          <strong>{{ item.title }}</strong><small>{{ displayTime(item.last_message_at || item.updated_at) }}</small>
        </button>
        <div class="conversation-actions">
          <button type="button" title="重命名" :disabled="disabled" @click="emit('rename', item)">编辑</button>
          <button type="button" title="删除" :disabled="disabled" @click="emit('remove', item)">删除</button>
        </div>
      </li>
    </ul>
  </aside>
</template>
