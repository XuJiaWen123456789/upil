"""低敏感稳定偏好的确定性取值工具。

本模块只负责从一条已经脱敏的用户消息中提取受控值，不执行数据库写入，
也不决定 LangGraph 路由。聊天回复和长期记忆准入复用同一套时间偏好解析，
可以避免出现“回复理解为周末上午、入库却解析成另一个值”的规则漂移。
"""

from __future__ import annotations

import re


_UNCERTAIN_MARKERS = (
    "可能", "也许", "大概", "好像", "不确定", "不知道", "考虑一下", "再看看",
)
_TRANSIENT_MARKERS = (
    "今天", "明天", "后天", "这周", "本周", "这一次", "这次", "暂时", "先看看", "最近考虑",
)
_TIME_CONTEXT_MARKERS = ("上课", "时间", "时段", "方便", "有空", "安排")
_STABLE_TIME_MARKERS = (
    "平时", "通常", "一般", "长期", "固定", "只有", "每周",
    "以后", "优先", "偏好", "希望", "尽量", "方便", "喜欢",
)
_TIME_VALUE_PATTERN = re.compile(
    r"(?:每周)?(?:工作日|平日|周末|周[一二三四五六日天]|星期[一二三四五六日天])"
    r"(?:早上|上午|中午|下午|晚上|晚间)?|(?:早上|上午|中午|下午|晚上|晚间)"
)


def extract_class_time_preference(message: str, *, explicit: bool = False) -> str | None:
    """提取稳定的上课时间偏好，临时安排和不确定表达返回 ``None``。

    ``explicit`` 只表示用户明确要求记忆，不会放宽“明天上午”等临时信息的
    拦截。普通陈述必须同时包含稳定性语义，例如“平时、每周、方便”。
    """

    if any(marker in message for marker in (*_UNCERTAIN_MARKERS, *_TRANSIENT_MARKERS)):
        return None
    match = _TIME_VALUE_PATTERN.search(message)
    if not match or not any(marker in message for marker in _TIME_CONTEXT_MARKERS):
        return None
    if not explicit and not any(marker in message for marker in _STABLE_TIME_MARKERS):
        return None
    return match.group(0).strip()
