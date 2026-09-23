import type { ReportDetail, ReportListResponse, ReportSummary } from "@/types/api";
import { requestJson } from "@/api/client";
import { withDemoIdentity } from "@/api/identity";

export function listReports(limit = 10, offset = 0): Promise<ReportListResponse> {
  return requestJson<ReportListResponse>("/api/v1/reports?limit=" + limit + "&offset=" + offset);
}

/**
 * 家长显式入口与聊天意图最终调用同一个后端报告执行服务。
 * 页面只提交自然语言周期，不能覆盖服务端计算出的日期范围和统计口径。
 */
export function generateParentReport(learnerId: string, period: string): Promise<ReportSummary> {
  return requestJson<ReportSummary>(
    "/api/v1/learners/" + encodeURIComponent(learnerId) + "/reports",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period }),
    },
  );
}

/** 教师报告也只接受自然语言周期，低课时阈值由后端固定为统一规则。 */
export function generateClassReport(classId: string, period: string): Promise<ReportSummary> {
  return requestJson<ReportSummary>(
    "/api/v1/classes/" + encodeURIComponent(classId) + "/reports",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ period }),
    },
  );
}

export function listClassReports(
  classId: string,
  limit = 10,
  offset = 0,
): Promise<ReportListResponse> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson<ReportListResponse>(
    "/api/v1/classes/" + encodeURIComponent(classId) + "/reports?" + query.toString(),
  );
}

export function getReport(taskId: string): Promise<ReportDetail> {
  return requestJson<ReportDetail>("/api/v1/reports/" + encodeURIComponent(taskId));
}

export interface DownloadedReport {
  blob: Blob;
  filename: string | null;
}

/** 下载始终走 FastAPI 鉴权代理，不直接访问 MinIO，也不处理预签名 URL。 */
export async function downloadReport(taskId: string): Promise<DownloadedReport> {
  const response = await fetch(withDemoIdentity("/api/v1/reports/" + encodeURIComponent(taskId) + "/download"), {
    credentials: "same-origin",
    headers: { Accept: "application/pdf, text/markdown" },
  });
  if (!response.ok) {
    let detail = "下载失败（HTTP " + response.status + "）";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // 非 JSON 错误继续使用固定通用文案。
    }
    throw new Error(detail);
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(response.headers.get("Content-Disposition")),
  };
}

/** 仅接受服务端固定字符集的文件名，不把任意响应头直接作为本地下载路径。 */
function parseDownloadFilename(header: string | null): string | null {
  if (!header) return null;
  const match = /filename="([A-Za-z0-9_.:-]{3,120})"/i.exec(header);
  return match?.[1] ?? null;
}

export { parseDownloadFilename };
