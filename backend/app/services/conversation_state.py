"""开发期会话状态与结构化路由规划。

本模块只在内存中保存最近确认的轻量实体，不保存知识正文、模型回答或
学员隐私数据。生产环境应使用 Redis 或 LangGraph PostgreSQL Checkpointer
替换该实现，以支持多进程、重启恢复和集中式过期治理。

这里的会话状态是“对话理解状态”，不是业务事实缓存。课程名称可以帮助
下一轮追问完成指代消解，但剩余课时、班级名额、退费金额等事实仍必须每次
从授权的业务系统读取，不能因为曾经出现在会话里就被视为可信结果。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
import re
from threading import RLock
import time
from typing import Callable

from backend.app.conversation_understanding import (
    EntityReference,
    EntityType,
    IntentResult,
    IntentType,
    CLASS_ALIASES,
    resolve_turn,
)
from backend.app.services.intent_recognition import (
    RecognitionSource,
    StructuredIntentModel,
    recognize_intent_detailed,
)


@dataclass(slots=True)
class ConversationMemory:
    """单个会话当前允许持久化的最小状态。"""

    # 只保存最近确认的实体引用，例如“编程项目实践班”，不保存知识正文。
    active_entity: EntityReference | None = None
    updated_at: float = field(default_factory=time.monotonic)
    # 每个会话使用独立锁；同一会话的并发请求串行化，不阻塞其他会话。
    lock: RLock = field(default_factory=RLock, repr=False)


@dataclass(frozen=True, slots=True)
class ConversationPlan:
    """一次请求进入 LangGraph 前的受控理解结果。

    该对象把“理解”和“执行”隔离开：路由层只提供受控计划，后续节点仍要
    自己完成权限校验和参数校验，不能把计划中的实体名称直接当作数据库主键。
    """

    conversation_id: str | None
    intent_result: IntentResult
    active_entity: EntityReference | None
    rewritten_query: str
    recognition_source: RecognitionSource
    # route 最终由 route_for_intent 的白名单映射产生，不接受模型任意字符串。
    route: str
    # 班级统计参数在这里完成一次结构化落地；后续 LangGraph 节点不再从
    # 用户原文猜日期或班级，避免模型/文本直接影响数据库查询范围。
    class_id: str | None = None
    class_name: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    low_balance_threshold: int = 5


class StatisticsPeriodError(ValueError):
    """统计周期存在但无法解析为合法日期时抛出的受控异常。"""


CLASS_DISPLAY_NAMES = {
    class_id: aliases[0]
    for class_id, aliases in CLASS_ALIASES.items()
}


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回指定月份的首日和末日，并统一拦截非法月份。"""

    if not 1 <= month <= 12:
        raise StatisticsPeriodError("月份必须在 1 至 12 之间")
    try:
        first = date(year, month, 1)
    except ValueError as exc:
        raise StatisticsPeriodError("统计月份不是合法日期") from exc
    return first, date(year, month, calendar.monthrange(year, month)[1])


def _parse_full_dates(text: str) -> list[date]:
    """提取完整日期，支持中文日期、短横线和斜线格式。"""

    pattern = re.compile(
        r"(?<!\d)(\d{4})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})\s*日?"
    )
    result: list[date] = []
    for match in pattern.finditer(text):
        try:
            result.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError as exc:
            raise StatisticsPeriodError("统计日期不是合法日期") from exc
    return result


def parse_statistics_period(
    message: str,
    *,
    reference_date: date | None = None,
) -> tuple[date, date] | None:
    """把用户给出的统计周期转换成闭区间日期。

    支持本项目演示中会出现的自然语言范围：月份、明确起止日期、
    本月/上个月、最近 7 天和最近 30 天。函数只负责解析，不访问数据库。
    这样做可以在真正查询前拦截反向日期、非法日期和不支持的表达。

    reference_date 只用于测试和回放；生产调用默认使用服务端日期，不能
    使用模型生成的“当前日期”，否则同一请求可能因模型输出而产生不同结果。
    """

    text = message.strip()
    if not text:
        return None
    today = reference_date or date.today()

    if "本月" in text or "这个月" in text:
        return today.replace(day=1), today
    if "上个月" in text or "上月" in text:
        previous = today.replace(day=1) - timedelta(days=1)
        return _month_range(previous.year, previous.month)
    if "最近7天" in text or "近7天" in text:
        return today - timedelta(days=6), today
    if "最近30天" in text or "近30天" in text:
        return today - timedelta(days=29), today

    full_dates = _parse_full_dates(text)
    if len(full_dates) >= 2:
        start, end = full_dates[0], full_dates[1]
        if start > end:
            raise StatisticsPeriodError("统计开始日期不能晚于结束日期")
        return start, end
    if len(full_dates) == 1:
        return full_dates[0], full_dates[0]

    # 只有月份、没有日时按整月统计。完整日期优先，所以不会把
    # “2026-08-01”误识别成 2026 年 8 月。
    month_match = re.search(r"(?<!\d)(\d{4})\s*(?:年\s*(\d{1,2})\s*月|[-/](\d{1,2}))(?![-/]\d)", text)
    if month_match:
        month = int(month_match.group(2) or month_match.group(3))
        return _month_range(int(month_match.group(1)), month)

    # 只要看起来像用户在写日期，就不要静默当成“未提供周期”。
    # 这会让非法月份/日期进入澄清，而不是错误调用业务工具。
    if re.search(r"\d{4}\s*(?:年|[-/])", text):
        raise StatisticsPeriodError("无法识别统计周期，请使用 YYYY-MM-DD 或 YYYY年M月")
    return None


def parse_low_balance_threshold(message: str, *, default: int = 5) -> int:
    """解析可选的低课时阈值；未说明时使用后端固定默认值。"""

    match = re.search(r"(?:低课时(?:阈值|提醒)?|剩余课时(?:不超过|少于等于))\s*(?:为|是|设为)?\s*(\d+)", message)
    if not match:
        return default
    threshold = int(match.group(1))
    if not 0 <= threshold <= 10000:
        raise ValueError("低课时阈值必须在 0 至 10000 之间")
    return threshold


def route_for_intent(result: IntentResult) -> str:
    """把业务意图白名单映射为当前真正可执行的工作流路由。

    当前只有学情查询具备实时数据库工具。其他需要实时数据的请求不能
    降级成静态 FAQ，而是进入人工兜底，防止模型编造名额或退款金额。
    """

    # 澄清优先级最高。即使模型识别出了某个意图，只要关键实体或周期不完整，
    # 就不能继续调用工具，否则会产生“查错人、查错班、查错周期”的业务事故。
    if result.clarification_needed:
        return "clarification"
    if result.intent == IntentType.LEARNING_REPORT:
        return "learning_report"
    if result.intent == IntentType.CLASS_LEARNING_SUMMARY:
        # 班级统计和个人学情是两条不同的数据权限链路，必须使用独立路由。
        return "class_learning_summary"
    if result.intent == IntentType.LEARNING_SUMMARY:
        return "learning_summary"
    if result.intent in {IntentType.COMPLAINT, IntentType.HUMAN_HANDOFF}:
        return "human_handoff"
    if result.needs_live_data:
        # 没有对应的实时工具时只能人工兜底，不能让静态 FAQ “看起来像是”
        # 查到了实时数据。这个分支是防止模型幻觉的重要最后一道路由门禁。
        return "human_handoff"
    if result.intent in {
        IntentType.SERVICE_RULES,
        IntentType.FEE_REFUND,
        IntentType.SAFETY_HEALTH,
        IntentType.CLASS_TRANSFER,
    }:
        return "service_rules"
    return "faq"


class InMemoryConversationStore:
    """带容量和过期限制的开发期进程内会话存储。

    `process` 在单会话锁内完成读取、模型识别和状态更新，从而避免同一
    conversation_id 的并发请求用旧实体相互覆盖。不同会话仍可并行处理。
    """

    def __init__(self, *, ttl_seconds: float = 1800, max_entries: int = 10000) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("会话 TTL 和容量必须为正数")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, ConversationMemory] = {}
        self._lock = RLock()

    def _prune_locked(self, now: float) -> None:
        """删除过期会话，并在超容量时优先移除最久未更新项。"""

        expired = [
            key
            for key, value in self._entries.items()
            if now - value.updated_at >= self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
        while len(self._entries) >= self.max_entries:
            oldest = min(self._entries, key=lambda key: self._entries[key].updated_at)
            self._entries.pop(oldest, None)

    def _entry(self, conversation_id: str) -> ConversationMemory:
        """返回有效会话；已过期会话会被当作新会话创建。"""

        now = time.monotonic()
        with self._lock:
            current = self._entries.get(conversation_id)
            if current is not None and now - current.updated_at < self.ttl_seconds:
                return current
            if current is not None:
                self._entries.pop(conversation_id, None)
            self._prune_locked(now)
            current = ConversationMemory(updated_at=now)
            self._entries[conversation_id] = current
            return current

    def process(
        self,
        conversation_id: str | None,
        processor: Callable[[EntityReference | None], ConversationPlan],
    ) -> ConversationPlan:
        """以会话安全方式执行规划；无 ID 的请求保持无状态兼容。"""

        if conversation_id is None:
            # 没有会话 ID 时不强行共享历史，兼容无状态 API 调用并避免把
            # 一个用户的实体错误地带入另一个用户的请求。
            return processor(None)
        entry = self._entry(conversation_id)
        with entry.lock:
            plan = processor(entry.active_entity)
            entity = plan.intent_result.mentioned_entity
            # 未知、低置信或需要澄清的实体不得污染后续对话。
            if (
                entity is not None
                and entity.entity_type != EntityType.UNKNOWN
                and not plan.intent_result.clarification_needed
            ):
                entry.active_entity = entity
            # 更新时间放在处理成功返回计划之后；过期淘汰依据的是最近一次
            # 有效交互，而不是某个尚未完成的并发请求。
            entry.updated_at = time.monotonic()
            return plan

    def clear(self) -> None:
        """清空开发期状态，主要用于测试隔离和本地调试。"""

        with self._lock:
            self._entries.clear()


def plan_conversation(
    message: str,
    *,
    conversation_id: str | None,
    store: InMemoryConversationStore,
    model: StructuredIntentModel | None = None,
) -> ConversationPlan:
    """结合历史实体生成意图、独立检索问题和安全路由。

    rewritten_query 面向检索，route 面向工作流，active_entity 面向下一轮
    对话；三者职责不同，不能用一个“大而全”的字符串替代结构化状态。
    """

    def build(active_entity: EntityReference | None) -> ConversationPlan:
        turn = resolve_turn(message, active_entity)
        outcome = recognize_intent_detailed(
            message, active_entity=active_entity, model=model
        )
        result = outcome.result
        next_entity = result.mentioned_entity or active_entity
        class_id: str | None = None
        class_name: str | None = None
        period_start: date | None = None
        period_end: date | None = None
        low_balance_threshold = 5

        # 只有已经被 Supervisor 识别为班级统计时才解析统计参数；普通 FAQ
        # 不应因为正文里出现一个年份或数字而被误判为数据库查询。
        if result.intent == IntentType.CLASS_LEARNING_SUMMARY:
            if next_entity is not None and next_entity.entity_type == EntityType.CLASS:
                class_id = next_entity.entity_name
                class_name = CLASS_DISPLAY_NAMES.get(class_id or "")
            try:
                period = parse_statistics_period(message)
                if period is not None:
                    period_start, period_end = period
                low_balance_threshold = parse_low_balance_threshold(message)
            except (StatisticsPeriodError, ValueError):
                # 非法周期/阈值只能进入澄清，不能让图节点带着不完整参数
                # 调用数据库。异常正文不向用户回显，统一使用安全提示。
                result = result.model_copy(update={"clarification_needed": True})

        return ConversationPlan(
            conversation_id=conversation_id,
            intent_result=result,
            active_entity=next_entity,
            rewritten_query=turn.rewritten_query,
            recognition_source=outcome.source,
            route=route_for_intent(result),
            class_id=class_id,
            class_name=class_name,
            period_start=period_start,
            period_end=period_end,
            low_balance_threshold=low_balance_threshold,
        )

    return store.process(conversation_id, build)
