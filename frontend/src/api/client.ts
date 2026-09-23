import type { FrontendBootstrap, SessionInfo } from "@/types/api";
import { withDemoIdentity } from "@/api/identity";

/** 统一封装 JSON 请求和安全错误文案，不把后端内部地址或异常正文泄露给浏览器。 */
export async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const normalizedInput = typeof input === "string" ? withDemoIdentity(input) : input;
  const response = await fetch(normalizedInput, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) throw new ApiError(response.status, await safeErrorMessage(response));
  return (await response.json()) as T;
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function safeErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : "请求失败（HTTP " + response.status + "）";
  } catch {
    return "请求失败（HTTP " + response.status + "）";
  }
}

export function getBootstrap(): Promise<FrontendBootstrap> {
  return requestJson<FrontendBootstrap>("/api/v1/frontend/bootstrap");
}

export function getSession(): Promise<SessionInfo> {
  // Demo 身份由 requestJson -> withDemoIdentity 统一附加；可信 Header/OIDC
  // 模式则保持无参数请求，不能让浏览器传入的角色字段参与认证。
  return requestJson<SessionInfo>("/api/v1/session");
}
