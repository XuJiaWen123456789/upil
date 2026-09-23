"""不调用大模型的确定性会话标题生成。"""

import re

from backend.app.conversations.redaction import redact_persistent_text


_COURSE_NAMES = (
    "舞蹈启蒙班", "中国舞基础班", "中国舞进阶班",
    "少儿美术创意班", "素描基础班", "音乐启蒙班",
    "童声合唱班", "少儿编程基础班", "编程项目实践班",
)


def generate_conversation_title(message: str) -> str:
    """根据首条脱敏消息生成短标题，失败时安全退回“新会话”。"""

    text = redact_persistent_text(message, max_length=200)
    compact = re.sub(r"[\s\r\n]+", "", text)
    if not compact or compact.startswith("[联系方式已"):
        return "新会话"
    course = next((name for name in _COURSE_NAMES if name in compact), None)
    if course and any(word in compact for word in ("试听", "预约", "报名")):
        return f"{course}试听咨询"[:80]
    if course:
        return f"{course}咨询"[:80]
    if "学习报告" in compact or "学情报告" in compact:
        return "孩子学情报告"
    if any(word in compact for word in ("学习情况", "出勤", "课时")):
        return "孩子学习情况查询"
    if "请假" in compact:
        return "课程请假咨询"
    # 去掉常见寒暄和弱语气，避免列表里出现大量“你好请问”。
    compact = re.sub(r"^(?:你好|您好|请问|我想|想了解|帮我)+", "", compact)
    return (compact[:20] or "新会话")
