<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { downloadReport, getReport } from "@/api/reports";
import type { ReportDetail } from "@/types/api";

const route = useRoute();
const report = ref<ReportDetail | null>(null);
const loading = ref(true);
const downloading = ref(false);
const error = ref("");
const statusLabels: Record<string, string> = {
  pending: "等待处理",
  running: "生成中",
  completed: "已完成",
  failed: "生成失败",
  cancelled: "已取消",
};
const isClassReport = computed(
  () => report.value?.task_type === "teacher_class_learning_report",
);
const pageTitle = computed(() =>
  isClassReport.value ? "班级学情报告详情" : "学生学情报告详情",
);

async function load() {
  try {
    report.value = await getReport(String(route.params.taskId));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "报告暂时不可用";
  } finally {
    loading.value = false;
  }
}

async function download() {
  if (!report.value) return;
  downloading.value = true;
  error.value = "";
  try {
    const downloaded = await downloadReport(report.value.task_id);
    const url = URL.createObjectURL(downloaded.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = downloaded.filename
      || (isClassReport.value ? "class-learning-report-" : "learning-report-")
        + report.value.task_id + ".pdf";
    anchor.click();
    URL.revokeObjectURL(url);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "报告下载失败";
  } finally {
    downloading.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <div v-if="loading" class="empty-state"><h2>正在读取报告详情</h2></div>
  <div v-else-if="error && !report" class="empty-state"><h2>报告不可用</h2><p>{{ error }}</p></div>
  <template v-else-if="report">
    <div class="page-heading">
      <div>
        <span class="eyebrow">REPORT DETAIL</span>
        <h1>{{ pageTitle }}</h1>
        <p>{{ report.period_start }} 至 {{ report.period_end }} · {{ statusLabels[report.status] }}</p>
      </div>
      <button class="button primary" :disabled="!report.download_available || downloading" @click="download">
        {{ downloading ? "准备下载" : "安全下载" }}
      </button>
    </div>
    <p v-if="error" class="alert">{{ error }}</p>
    <p v-if="!report.download_available" class="alert">
      {{ report.message }} 下载入口只会在服务端确认报告完整可用后出现。
    </p>
    <section class="grid grid-3">
      <div class="panel metric"><span class="metric-label">生成状态</span><strong class="metric-value compact-value">{{ statusLabels[report.status] }}</strong></div>
      <div class="panel metric"><span class="metric-label">模板版本</span><strong class="metric-value compact-value">{{ report.template_version || "历史版本" }}</strong></div>
      <div class="panel metric"><span class="metric-label">产物数量</span><strong class="metric-value">{{ report.artifacts.length }}</strong><span class="metric-note">正文和对象地址不会下发</span></div>
    </section>
  </template>
</template>
