<script setup lang="ts">
import { ref } from "vue";
import { getLearningSnapshot } from "@/api/learning";
import type { LearningSnapshot } from "@/types/api";

const learnerId = ref("L1001");
const snapshot = ref<LearningSnapshot | null>(null);
const error = ref("");
const loading = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try { snapshot.value = await getLearningSnapshot(learnerId.value.trim()); }
  catch (cause) { snapshot.value = null; error.value = cause instanceof Error ? cause.message : "学情暂时不可用"; }
  finally { loading.value = false; }
}

function percent(value: number) { return Math.round(value * 100) + "%"; }
</script>

<template>
  <div class="page-heading"><div><span class="eyebrow">PARENT LEARNING</span><h1>孩子学情</h1><p>仅查询当前家长绑定且经过后端授权的学员快照。</p></div></div>
  <section class="panel panel-pad toolbar"><label class="field" style="min-width:220px"><span>学员编号</span><input v-model="learnerId" maxlength="64" /></label><button class="button primary" :disabled="loading" @click="load">{{ loading ? "查询中" : "查询学情" }}</button></section>
  <p v-if="error" class="alert">{{ error }}</p>
  <template v-if="snapshot">
    <div class="grid grid-3" style="margin-top:18px"><section class="panel metric"><span class="metric-label">学员</span><strong class="metric-value" style="font-size:22px">{{ snapshot.profile.learner_name }}</strong><span class="metric-note">{{ snapshot.profile.learner_id }}</span></section><section class="panel metric"><span class="metric-label">剩余课时</span><strong class="metric-value">{{ snapshot.balance.remaining_hours }}</strong><span class="metric-note">已消耗 {{ snapshot.balance.consumed_hours }} / 总计 {{ snapshot.balance.total_hours }}</span></section><section class="panel metric"><span class="metric-label">出勤率</span><strong class="metric-value">{{ percent(snapshot.attendance.attendance_rate) }}</strong><span class="metric-note">出勤 {{ snapshot.attendance.present_lessons }} · 缺勤 {{ snapshot.attendance.absent_lessons }}</span></section></div>
    <section class="panel panel-pad" style="margin-top:18px"><div class="page-heading" style="margin-bottom:15px"><div><span class="eyebrow">PUBLISHED PROGRESS</span><h2>阶段进度</h2></div></div><div class="grid grid-2"><article v-for="item in snapshot.progress" :key="item.course_name" class="panel panel-pad"><h3>{{ item.course_name }}</h3><p>{{ item.current_stage }}</p><div class="progress"><i :style="{ width: percent(item.completion_rate) }" /></div><small>{{ percent(item.completion_rate) }}</small><ul class="list" style="margin-top:12px"><li>优势：{{ item.strengths.join("、") || "暂无" }}</li><li>下一步：{{ item.next_focus.join("、") || "暂无" }}</li></ul></article></div></section>
  </template>
  <section v-else-if="!loading" class="empty-state"><span class="eyebrow">LEARNING SNAPSHOT</span><h2>输入学员编号开始查询</h2><p>报告和学情接口会在后端再次执行家长绑定校验。</p></section>
</template>
