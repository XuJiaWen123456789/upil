"""应用运行时共享对象。

配置对象和会话存储客户端必须是进程内唯一实例。除了避免重复创建资源，
这也保证 FastAPI 路由、兼容入口和测试通过 main.settings 修改配置时，
最终使用的是同一个可变配置对象。
"""

from backend.app.config import get_settings
from backend.app.memory.conversation.factory import build_conversation_store


# 应用启动时创建一次配置，路由与依赖工厂均从这里读取。
settings = get_settings()

# 由工厂根据配置选择短期会话后端。Redis 初始化失败时直接抛出配置/依赖
# 错误，不能悄悄回退到进程内存，否则多进程部署会把会话拆成不一致的副本。
conversation_store = build_conversation_store(settings)
