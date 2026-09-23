import { requestJson } from "@/api/client";
import { withDemoIdentity } from "@/api/identity";
import type {
  ConversationListResponse,
  ConversationMessagesResponse,
  ConversationSummary,
} from "@/types/api";

/** 创建空会话。所有者由服务端认证上下文决定，前端不能传入用户 ID。 */
export function createConversation(title?: string): Promise<ConversationSummary> {
  return requestJson<ConversationSummary>("/api/v1/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  });
}

/** 只读取当前身份自己的会话目录，默认按最近活动倒序。 */
export function listConversations(
  limit = 100,
  offset = 0,
): Promise<ConversationListResponse> {
  return requestJson<ConversationListResponse>(
    `/api/v1/conversations?limit=${limit}&offset=${offset}`,
  );
}

/** 页面只恢复 PostgreSQL 中已脱敏的可见消息，不读取 Redis 原始状态。 */
export function getConversationMessages(
  conversationId: string,
  limit = 200,
): Promise<ConversationMessagesResponse> {
  return requestJson<ConversationMessagesResponse>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`,
  );
}

/** 用户手动重命名后，服务端会阻止自动标题再次覆盖。 */
export function renameConversation(
  conversationId: string,
  title: string,
): Promise<ConversationSummary> {
  return requestJson<ConversationSummary>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    },
  );
}

/** 删除会话目录与消息；线索、报告和长期偏好由后端保持独立。 */
export async function deleteConversation(conversationId: string): Promise<void> {
  const response = await fetchWithIdentity(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error("删除会话失败，请稍后重试。");
}

// DELETE 返回 204，不能复用要求 JSON 响应体的 requestJson。
function fetchWithIdentity(path: string, init: RequestInit): Promise<Response> {
  return fetch(withDemoIdentity(path), { credentials: "same-origin", ...init });
}
