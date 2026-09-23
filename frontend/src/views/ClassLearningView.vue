<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getClassSummary } from "@/api/learning";
import { generateClassReport, listClassReports } from "@/api/reports";
import { useSessionStore } from "@/stores/session";
import type { ClassLearningSummary, ReportSummary } from "@/types/api";
import { formatApiDateTime } from "@/utils/datetime";

const router = useRouter();
const sessionStore = useSessionStore();
const classId = ref("CLASS_DANCE_01");
const period = ref("最近30天");
const summary = ref<ClassLearningSummary | null>(null);
const reports = ref<ReportSummary[]>([]);
const total = ref(0);
const error = ref("");
const notice = ref("");
const loading = ref(false);
const statusLabels: Record<string, string> = {
  pending: "等待处理", running: "生成中", completed: "已完成",
  failed: "生成失败", cancelled: "已取消",
};

function percent(value: number) { return Math.round(value * 100) + "%"; }
function statusClass(status: string) {
  return status === "completed" ? "badge"
    : status === "failed" || status === "cancelled" ? "badge danger" : "badge warn";
}

async function loadReports() {
  const value = classId.value.trim();
  if (!value) return;
  error.value = "";
  try {
    const result = await listClassReports(value);
    reports.value = result.items;
    total.value = result.total;
  } catch (cause) {
    reports.value = [];
    error.value = cause instanceof Error ? cause.message : "班级报告暂时不可用";
  }
}

async function generate() {
  const value = classId.value.trim();
  const requestedPeriod = period.value.trim();
  if (!value || !requestedPeriod) {
    error.value = "请填写班级编号和报告周期";
    return;
  }
  loading.value = true;
  error.value = "";
  notice.value = "";
  try {
    const task = await generateClassReport(value, requestedPeriod);
    notice.value = task.status === "completed"
      ? "班级报告已生成，可在历史列表中下载。" : task.message;
    if (task.period_start && task.period_end) {
      // 浏览器不解析自然语言日期，只使用后端返回的权威周期读取统计。
      summary.value = await getClassSummary(value, task.period_start, task.period_end, 5);
    }
    await loadReports();
  } catch (cause) {
    summary.value = null;
    error.value = cause instanceof Error ? cause.message : "班级报告生成失败";
  } finally {
    loading.value = false;
  }
}

function openReport(report: ReportSummary) {
  void router.push("/teacher/reports/" + encodeURIComponent(report.task_id));
}
onMounted(() => void loadReports());
</script>

<template>
  <div class="page-heading">
    <div><span class="eyebrow">TEACHER CLASS ANALYTICS</span><h1>班级学情统计</h1><p>指标由后端固定计算，教师只能读取已授权校区与授课班级。</p></div>
  </div>
  <section class="panel panel-pad toolbar">
    <label class="field"><span>班级编号</span><input v-model="classId" maxlength="64" /></label>
    <label class="field period-field"><span>报告周期</span><input v-model="period" maxlength="100" placeholder="例如：上个月、最近30天、2026年8月" /></label>
    <button class="button primary" :disabled="loading || !sessionStore.featureEnabled('pdf_reports')" @click="generate">{{ loading ? "生成中" : "生成班级报告" }}</button>
    <button class="button secondary" :disabled="loading" @click="loadReports">刷新历史</button>
    <span v-if="!sessionStore.featureEnabled('pdf_reports')" class="metric-note">当前环境未启用 PDF 报告服务</span>
  </section>
  <p v-if="error" class="alert">{{ error }}</p>
  <p v-if="notice" class="notice">{{ notice }}</p>

  <template v-if="summary">
    <div class="grid grid-3 section-gap">
      <div class="panel metric"><span class="metric-label">班级</span><strong class="metric-value compact-value">{{ summary.class_name }}</strong><span class="metric-note">{{ summary.course_name }} · {{ summary.campus_name }}</span></div>
      <div class="panel metric"><span class="metric-label">出勤率</span><strong class="metric-value">{{ percent(summary.attendance_rate) }}</strong><span class="metric-note">出勤 {{ summary.attended_records }} · 缺勤 {{ summary.absent_records }}</span></div>
      <div class="panel metric"><span class="metric-label">未登记考勤</span><strong class="metric-value">{{ summary.unmarked_records }}</strong><span class="metric-note">共 {{ summary.enrolled_learners }} 名学员</span></div>
    </div>
    <section class="panel panel-pad section-gap">
      <div class="page-heading compact-heading"><div><span class="eyebrow">ABSENCE TOP 5</span><h2>缺勤关注</h2></div><span class="badge">周期 {{ summary.period_start }} 至 {{ summary.period_end }}</span></div>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>学员</th><th>缺勤</th><th>出勤率</th><th>剩余课时</th></tr></thead><tbody><tr v-for="item in summary.absence_top5" :key="item.learner_id"><td>{{ item.learner_name }}</td><td>{{ item.absent_lessons }}</td><td>{{ percent(item.attendance_rate) }}</td><td>{{ item.remaining_hours ?? "—" }}</td></tr></tbody></table></div>
    </section>
    <section class="panel panel-pad section-gap"><span class="eyebrow">LOW BALANCE</span><h2>低课时提醒</h2><ul class="list"><li v-for="item in summary.low_balance_learners" :key="item.learner_id">{{ item.learner_name }} · 剩余 {{ item.remaining_hours ?? "未知" }} 课时</li><li v-if="!summary.low_balance_learners.length">当前没有低于固定规则的学员。</li></ul></section>
  </template>

  <section class="panel stack report-list section-gap">
    <div class="page-heading compact-heading"><div><span class="eyebrow">REPORT HISTORY</span><h2>班级报告历史</h2></div><span class="metric-note">共 {{ total }} 份</span></div>
    <div v-if="!reports.length && !loading" class="empty-state compact-empty"><h2>暂无班级报告</h2><p>生成后的 PDF 会显示在这里。</p></div>
    <article v-for="report in reports" :key="report.task_id" class="report-card">
      <div><h3>{{ report.period_start || "报告周期待定" }}<span v-if="report.period_end"> 至 {{ report.period_end }}</span></h3><p>{{ report.message }} · {{ formatApiDateTime(report.created_at) }}</p></div>
      <div class="report-actions"><span :class="statusClass(report.status)">{{ statusLabels[report.status] || report.status }}</span><button class="button secondary" @click="openReport(report)">查看详情</button></div>
    </article>
  </section>
</template>
