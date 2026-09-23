import type { ClassLearningSummary, LearningSnapshot } from "@/types/api";
import { requestJson } from "@/api/client";

export function getLearningSnapshot(learnerId: string): Promise<LearningSnapshot> {
  return requestJson<LearningSnapshot>("/api/v1/learners/" + encodeURIComponent(learnerId) + "/learning-snapshot");
}

export function getClassSummary(
  classId: string,
  periodStart: string,
  periodEnd: string,
  lowBalanceThreshold = 5,
): Promise<ClassLearningSummary> {
  const query = new URLSearchParams({
    period_start: periodStart,
    period_end: periodEnd,
    low_balance_threshold: String(lowBalanceThreshold),
  });
  return requestJson<ClassLearningSummary>(
    "/api/v1/classes/" + encodeURIComponent(classId) + "/learning-summary?" + query.toString(),
  );
}
