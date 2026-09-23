<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

const props = defineProps<{ open: boolean; initialTitle: string; saving: boolean }>();
const emit = defineEmits<{ close: []; save: [title: string] }>();
const title = ref("");
const input = ref<HTMLInputElement | null>(null);

watch(() => props.open, async (open) => {
  if (!open) return;
  title.value = props.initialTitle;
  await nextTick();
  input.value?.focus();
  input.value?.select();
});
</script>

<template>
  <div v-if="open" class="dialog-backdrop" role="presentation" @click.self="emit('close')">
    <form class="panel conversation-dialog" role="dialog" aria-modal="true" aria-label="重命名会话" @submit.prevent="emit('save', title.trim())">
      <h3>重命名会话</h3>
      <label class="field">会话名称<input ref="input" v-model="title" maxlength="80" required /></label>
      <div class="dialog-actions"><button class="button secondary" type="button" :disabled="saving" @click="emit('close')">取消</button><button class="button primary" type="submit" :disabled="saving || !title.trim()">{{ saving ? "保存中" : "保存" }}</button></div>
    </form>
  </div>
</template>
