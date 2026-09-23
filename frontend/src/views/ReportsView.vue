<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { generateParentReport, listReports } from "@/api/reports";
import { useSessionStore } from "@/stores/session";
import type { ReportSummary } from "@/types/api";
import { formatApiDateTime } from "@/utils/datetime";

const router = useRouter();
const sessionStore = useSessionStore();
const learnerId = ref("L1001");
const period = ref("最近30天");
const reports = ref<ReportSummary[]>([]);
const total = ref(0);
const offset = ref(0);
const limit = 10;
const loading = ref(false);
const generating = ref(false);
const error = ref("");
const notice = ref("");

const statusLabels: Record<string, string> = {
  pending: "等待处理", running: "生成中", completed: "已完成",
  failed: "生成失败", cancelled: "已取消",
};

function statusClass(status: string) {
  return status === "completed" ? "badge"
    : status === "failed" || status === "cancelled" ? "badge danger" : "badge warn";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const result = await listReports(limit, offset.value);
    reports.value = result.items;
    total.value = result.total;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "报告暂时不可用";
  } finally {
    loading.value = false;
  }
}

async function generate() {
  const learner = learnerId.value.trim();
  const requestedPeriod = period.value.trim();
  if (!learner || !requestedPeriod) {
    error.value = "请填写学员编号和报告周期";
    return;
  }
  generating.value = true;
  error.value = "";
  notice.value = "";
  try {
    const task = await generateParentReport(learner, requestedPeriod);
    notice.value = task.status === "completed"
      ? "报告已生成，可在列表中查看和下载。" : task.message;
    offset.value = 0;
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "报告生成失败";
  } finally {
    generating.value = false;
  }
}

function openReport(report: ReportSummary) {
  void router.push("/parent/reports/" + encodeURIComponent(report.task_id));
}
function previous() { if (offset.value >= limit) { offset.value -= limit; void load(); } }
function next() { if (offset.value + limit < total.value) { offset.value += limit; void load(); } }
onMounted(() => void load());
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">PARENT REPORTS</span><h1>学情报告</h1><p>报告由主系统生成，下载时再次完成家长身份与文件完整性校验。</p></div>
    <button class="button secondary" :disabled="loading" @click="load">刷新</button>
  </div>
  <section class="panel panel-pad toolbar">
    <label class="field"><span>学员编号</span><input v-model="learnerId" maxlength="64" /></label>
    <label class="field period-field"><span>报告周期</span><input v-model="period" maxlength="100" placeholder="例如：上个月、最近30天、2026年8月" /></label>
    <button class="button primary" :disabled="generating || !sessionStore.featureEnabled('pdf_reports')" @click="generate">{{ generating ? "生成中" : "生成报告" }}</button>
    <span v-if="!sessionStore.featureEnabled('pdf_reports')" class="metric-note">当前环境未启用 PDF 报告服务</span>
  </section>
  <p v-if="error" class="alert">{{ error }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>
  <section class="panel stack report-list">
    <div v-if="!reports.length && !loading" class="empty-state"><h2>暂无报告</h2><p>可以通过对话意图或上方按钮生成报告。</p></div>
    <article v-for="report in reports" :key="report.task_id" class="report-card">
      <div><h3>{{ report.period_start || "报告周期待定" }}<span v-if="report.period_end"> 至 {{ report.period_end }}</span></h3><p>{{ report.message }} · {{ formatApiDateTime(report.created_at) }}</p></div>
      <div class="report-actions"><span :class="statusClass(report.status)">{{ statusLabels[report.status] || report.status }}</span><button class="button secondary" @click="openReport(report)">查看详情</button></div>
    </article>
  </section>
  <div class="toolbar pagination">
    <span class="metric-note">共 {{ total }} 份 · 第 {{ total ? Math.floor(offset / limit) + 1 : 0 }} 页</span>
    <div><button class="button secondary" :disabled="offset === 0 || loading" @click="previous">上一页</button><button class="button secondary next-button" :disabled="offset + limit >= total || loading" @click="next">下一页</button></div>
  </div>
</template>
