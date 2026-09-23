import { requestJson } from "@/api/client";
import type {
  LeadContact,
  LeadDestination,
  LeadDetail,
  LeadFollowUp,
  LeadFollowUpInput,
  LeadListResponse,
} from "@/types/api";

/** 列表参数只允许后端定义的两个分流范围，不能传任意筛选表达式。 */
export function listLeads(
  destination: LeadDestination,
  limit = 50,
  offset = 0,
): Promise<LeadListResponse> {
  const query = new URLSearchParams({
    destination,
    limit: String(limit),
    offset: String(offset),
  });
  return requestJson<LeadListResponse>("/api/v1/leads?" + query.toString());
}

export function getLead(leadId: string): Promise<LeadDetail> {
  return requestJson<LeadDetail>("/api/v1/leads/" + encodeURIComponent(leadId));
}

/** 明文联系方式只能通过重新鉴权的专用接口读取，不进入普通详情缓存。 */
export function revealLeadContact(leadId: string): Promise<LeadContact> {
  return requestJson<LeadContact>(
    "/api/v1/leads/" + encodeURIComponent(leadId) + "/contact",
    { cache: "no-store" },
  );
}

export function addLeadFollowUp(
  leadId: string,
  payload: LeadFollowUpInput,
): Promise<LeadFollowUp> {
  return requestJson<LeadFollowUp>(
    "/api/v1/leads/" + encodeURIComponent(leadId) + "/follow-ups",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}
