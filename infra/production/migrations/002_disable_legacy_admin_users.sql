-- uPil 业务角色已收敛为家长和教师。
-- 历史管理员账号及其 OIDC 映射保留记录用于审计，但禁止继续登录。

BEGIN;

UPDATE users
SET is_active = FALSE
WHERE role = 'admin'
  AND is_active = TRUE;

UPDATE external_identities
SET is_active = FALSE
WHERE user_id IN (
    SELECT id
    FROM users
    WHERE role = 'admin'
);

COMMIT;
