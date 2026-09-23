"""对话式试听与报名意向旁路 Agent。

本模块只分析已经脱敏的文本并输出有限证据码，不访问数据库，也不决定
队列或联系方式写入。模型不可用、超时或返回非法结构时，确定性规则仍能
给出保守结果，主咨询链路不会依赖旁路 Agent 成功。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.conversation_understanding import (
    COURSE_ALIASES,
    COURSE_CATEGORIES,
    EntityType,
    extract_entity_reference,
)
from backend.app.prompts import load_prompt


EvidenceCode = Literal[
    "positive_interest",
    "request_more_information",
    "trial_process_question",
    "explicit_trial_request",
    "explicit_enrollment_request",
    "advisor_contact_request",
    "contact_consent",
    "explicit_decline",
]
InterestType = Literal["none", "trial", "enrollment", "unknown"]


class EnrollmentIntentResult(BaseModel):
    """旁路 Agent 的严格输出；不包含分数、工具参数或任意业务字段。"""

    interest_type: InterestType = "none"
    course_name: str | None = None
    evidence_codes: list[EvidenceCode] = Field(default_factory=list, max_length=8)
    source: Literal["model", "deterministic_fallback"] = "deterministic_fallback"

    model_config = ConfigDict(extra="forbid")


class EnrollmentIntentModel(Protocol):
    """兼容 LangChain ChatModel 和测试桩的最小协议。"""

    def invoke(self, prompt: str) -> Any:
        """返回结构化对象、字典或 JSON 文本。"""


_DECLINE_PATTERNS = (
    "不要联系我", "别联系我", "无需联系",
    # “联系我”本身是正向词，但前面出现“不用/暂时不用”时语义完全相反。
    # 否定表达必须在正向顾问联系规则之前命中，避免生成错误线索卡。
    "不用联系我", "暂时不用联系我", "先不用联系我",
    "暂时不联系我", "先不联系我", "不必联系我",
    "不考虑了",
    "不想报名", "不想试听", "取消意向", "撤回授权",
    # 家长在了解完试听流程后，常用“先不用安排”“暂时不预约”表示
    # 当前不希望继续推进，而不一定会说正式的“取消意向”。这些表达必须
    # 覆盖招生旁路，否则旧线索仍可能留在待跟进状态。
    "先不用安排", "暂时不用安排", "暂时不安排", "先不安排",
    "暂时不预约", "先不预约", "暂时不试听", "先不试听",
    "暂时不报名", "先不报名", "暂时不报课", "先不报课",
    "不同意联系", "不同意记录", "不同意保存",
)
_CONTACT_CONSENT_PATTERNS = (
    "同意记录", "同意保存", "同意联系", "授权联系",
    "同意由销售顾问", "同意销售顾问", "同意老师联系",
    "可以保存", "请用这个联系方式联系我", "请按这个号码联系我",
)
_ADVISOR_PATTERNS = ("顾问联系", "课程顾问联系", "安排顾问", "联系我")
_TRIAL_ACTION_PATTERNS = (
    "预约", "安排", "参加", "报名", "去试听", "去体验",
)
_ENROLLMENT_ACTION_PATTERNS = (
    "想报名", "我要报名", "现在报名", "直接报名",
    "准备报名", "想报课", "我要报课", "试听后报名", "试听和报名",
)
_TRIAL_QUESTION_PATTERNS = (
    "怎么试听", "如何试听", "试听流程", "试听需要",
    "怎么预约试听", "如何预约试听", "试听怎么参加", "试听条件",
    "有试听吗", "是否可以试听", "有试听课吗", "是否有试听课",
    "有体验课吗", "是否有体验课",
)
_POSITIVE_PATTERNS = ("感兴趣", "有兴趣", "考虑学习", "考虑报名", "想学")
_MORE_INFO_PATTERNS = ("想了解", "进一步了解", "详细介绍", "多了解")
_ACTION_EVIDENCE = {
    "explicit_trial_request",
    "explicit_enrollment_request",
    "advisor_contact_request",
    "contact_consent",
    "explicit_decline",
}


def _contains_any(message: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in message for pattern in patterns)


def has_explicit_enrollment_decline(message: str) -> bool:
    """判断家长是否明确拒绝或暂缓试听、报名及顾问联系。

    该函数同时供主对话状态机和招生旁路使用，避免两个链路各维护一套
    否定词，最终出现“页面回复已暂缓、后台线索却仍待跟进”的状态漂移。
    """

    return _contains_any(message, _DECLINE_PATTERNS)


def is_trial_process_question(message: str) -> bool:
    """识别试听规则咨询，不把它升级成明确预约动作。"""

    return _contains_any(message, _TRIAL_QUESTION_PATTERNS)


def has_explicit_trial_action(message: str) -> bool:
    """识别明确的试听动作，允许课程名和“试听”之间存在自然语言修饰。"""

    if not _contains_any(message, ("试听", "体验")):
        return False
    if is_trial_process_question(message):
        return False
    if _contains_any(message, _TRIAL_ACTION_PATTERNS):
        return True
    # “我想试听”“我要体验一下”是最短的明确表达；“我想了解试听
    # 流程”已在上面的流程问题分支拦截，不能仅凭“想+试听”判断预约。
    return bool(re.search(r"(?:我)?(?:想|要)\s*(?:去|参加)?\s*(?:试听|体验)", message))


def has_explicit_enrollment_action(message: str) -> bool:
    """识别明确报名动作，避免把“报名流程”误当成报名请求。"""

    # 中文里的“报名试听”通常表示报名参加试听，而不是直接购买正式课程；
    # 该表达由试听动作处理，不能同时升级成正式报名。
    if "报名试听" in message and not _contains_any(message, ("试听后报名", "试听和报名")):
        return False
    return _contains_any(message, _ENROLLMENT_ACTION_PATTERNS)


def _course_name(message: str) -> str | None:
    """只接受项目课程白名单或课程大类，模型不能创造课程名称。"""

    entity = extract_entity_reference(message)
    if entity and entity.entity_type in {EntityType.COURSE, EntityType.COURSE_CATEGORY}:
        return entity.entity_name
    return None


def deterministic_enrollment_intent(message: str) -> EnrollmentIntentResult:
    """从明确措辞提取证据；否定表达优先于所有正向关键词。"""

    evidence: list[EvidenceCode] = []
    if has_explicit_enrollment_decline(message):
        evidence.append("explicit_decline")
        return EnrollmentIntentResult(
            course_name=_course_name(message), evidence_codes=evidence
        )

    # “想了解试听流程”“怎么预约试听”是信息咨询，不是发起预约。
    # 试听/体验只有命中明确动作或直接表达“我想试听”时才升级；课程名、
    # 指代和助词可以出现在动作词与目标词之间。
    explicit_trial = has_explicit_trial_action(message)
    if explicit_trial:
        evidence.append("explicit_trial_request")
    explicit_enrollment = has_explicit_enrollment_action(message)
    if explicit_enrollment:
        evidence.append("explicit_enrollment_request")
    if _contains_any(message, _ADVISOR_PATTERNS):
        evidence.append("advisor_contact_request")
    if is_trial_process_question(message):
        evidence.append("trial_process_question")
    if _contains_any(message, _POSITIVE_PATTERNS):
        evidence.append("positive_interest")
    if _contains_any(message, _MORE_INFO_PATTERNS):
        evidence.append("request_more_information")
    if _contains_any(message, _CONTACT_CONSENT_PATTERNS):
        evidence.append("contact_consent")
    # 固定询问后的自然回复常写成“同意，我的手机号是……”。只有同一条
    # 已脱敏消息同时带联系方式占位符时，孤立的“同意”才视为明确授权。
    if (
        "[联系方式已脱敏]" in message
        and re.search(r"(?:^|[，,；;\s])(?:我)?同意(?:[，,。；;\s]|$)", message)
        and "contact_consent" not in evidence
    ):
        evidence.append("contact_consent")

    if "explicit_enrollment_request" in evidence:
        interest_type: InterestType = "enrollment"
    elif {"explicit_trial_request", "trial_process_question"} & set(evidence):
        interest_type = "trial"
    elif evidence:
        interest_type = "unknown"
    else:
        interest_type = "none"
    return EnrollmentIntentResult(
        interest_type=interest_type,
        course_name=_course_name(message),
        evidence_codes=list(dict.fromkeys(evidence)),
    )


def _message_content(output: Any) -> Any:
    if isinstance(output, Mapping):
        return dict(output)
    content = getattr(output, "content", output)
    if isinstance(content, list):
        return "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
        )
    return content


def _parse_model_output(output: Any) -> EnrollmentIntentResult:
    if isinstance(output, EnrollmentIntentResult):
        return output
    content = _message_content(output)
    if isinstance(content, Mapping):
        return EnrollmentIntentResult.model_validate(dict(content))
    if not isinstance(content, str):
        raise ValueError("意向模型没有返回结构化内容")
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    return EnrollmentIntentResult.model_validate(json.loads(text))


def _build_prompt(message: str) -> str:
    schema = EnrollmentIntentResult.model_json_schema()
    return (
        f"{load_prompt('enrollment_intent.txt')}\n"
        f"课程白名单：{json.dumps([*COURSE_ALIASES, *COURSE_CATEGORIES], ensure_ascii=False)}\n"
        f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n"
        f"待分析数据：{json.dumps(message, ensure_ascii=False)}"
    )


def analyze_enrollment_intent(
    message: str, *, model: EnrollmentIntentModel | None = None
) -> EnrollmentIntentResult:
    """合并模型和确定性证据，高风险动作始终要求文本规则直接命中。"""

    fallback = deterministic_enrollment_intent(message)
    if model is None or "explicit_decline" in fallback.evidence_codes:
        return fallback
    try:
        parsed = _parse_model_output(model.invoke(_build_prompt(message)))
        allowed_courses = {*COURSE_ALIASES, *COURSE_CATEGORIES}
        model_course = parsed.course_name if parsed.course_name in allowed_courses else None
        # 模型只可补充低风险兴趣证据；预约、报名、授权和拒绝都必须有
        # 确定性文本证据，避免 Prompt 注入直接推动业务状态。
        evidence = list(fallback.evidence_codes)
        for code in parsed.evidence_codes:
            if code not in _ACTION_EVIDENCE and code not in evidence:
                evidence.append(code)
        result = fallback.model_copy(
            update={
                "course_name": fallback.course_name or model_course,
                "evidence_codes": evidence,
                "source": "model",
            }
        )
        return result
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError, TimeoutError):
        return fallback
    except Exception:
        # 第三方 SDK 的连接或限流异常不能泄露，也不能影响正常咨询。
        return fallback
