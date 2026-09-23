let demoIdentity: { role: string; userId: string } | null = null;

/**
 * 本地身份模式下把当前身份附加到请求查询参数。
 *
 * 这不是生产认证方案：trusted_headers/OIDC 模式后端会忽略这些参数，
 * 真实认证模式下不会显示身份切换器。保留这一层是为了让本地多角色联调
 * 能够复用同一套接口，而不在每个页面重复拼接身份字段。
 */
export function setDemoIdentity(role: string, userId: string): void {
  demoIdentity = { role, userId };
}

export function clearDemoIdentity(): void {
  demoIdentity = null;
}

export function withDemoIdentity(path: string): string {
  if (!demoIdentity) return path;
  const separator = path.includes("?") ? "&" : "?";
  return path + separator + "actor_role=" + encodeURIComponent(demoIdentity.role)
    + "&actor_user_id=" + encodeURIComponent(demoIdentity.userId);
}

export function currentDemoIdentity(): { role: string; userId: string } | null {
  return demoIdentity;
}
