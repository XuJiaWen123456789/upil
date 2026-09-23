"""聊天会话目录、脱敏消息持久化与短期上下文恢复。

领域包初始化阶段不主动导入应用服务。ORM 元数据加载时会先导入
``conversations.models``，如果这里再反向导入依赖访问控制的 service，会形成
``models -> conversations -> service -> access_control -> models`` 循环。调用方应
从具体模块显式导入所需对象。
"""
