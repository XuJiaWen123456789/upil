-- 项目收尾：教师媒体工作台退出当前产品边界。
-- 历史 003 迁移保持不可变；本迁移只清理已经下线的能力授权与元数据表。
-- MinIO 中可能存在的历史图片对象由运维单独盘点，不在数据库事务中跨系统删除。

BEGIN;

-- 清理旧授权，避免历史账号继续携带前端和 API 已不再支持的权限。
DELETE FROM user_permissions
WHERE permission IN ('media_upload', 'media_review');

-- 报告 PDF 使用 report_artifacts，不依赖媒体资产表。
DROP TABLE IF EXISTS media_assets;

COMMIT;
