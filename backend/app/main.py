"""FastAPI 应用入口和 SSE 对话接口。

本模块负责 HTTP 边界、依赖注入、流式事件和演示环境适配，不负责让大模型
直接决定权限或计算动态学情。把这些职责留在服务/工具层，才能在更换模型、
RAGFlow 或远程 A2A/DSH 节点时保持核心业务口径稳定。
"""

import asyncio
import json
import logging
import re                                   #校验请求 ID
from collections.abc import AsyncIterator   #标注异步生成器类型
from pathlib import Path
from uuid import uuid4                      #生成请求追踪 ID

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware    #解决前后端跨域；
from fastapi.responses import StreamingResponse       #返回 SSE 流；
from fastapi.staticfiles import StaticFiles           #托管前端静态页面
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.db import get_session
from backend.app.integrations.minio import MinioMediaStore
from backend.app.integrations.llm import build_langchain_llm
from backend.app.integrations.a2a_client import LocalMockA2AClient
from backend.app.integrations.a2a_http_client import HttpA2ALearningClient
from backend.app.integrations.business_adapters import (
    ClassAvailabilityData,
    FakeBusinessSystemsAdapter,
)
from backend.app.graph import conversation_graph
from backend.app.models import AuditLog, MediaAsset
from backend.app.schemas import (
    ActorRole,
    ChatRequest,
    ClassLearningSummaryQuery,
    ClassLearningSummaryResponse,
    DemoClassAvailabilityRequest,
    HealthResponse,
    DependencyHealthResponse,
    LearningSnapshotResponse,
    MediaAssetResponse,
    MediaAssetUrlResponse,
    MediaReviewRequest,
    MediaVisibility,
)
from backend.app.tools.business_tools import (
    BusinessToolRegistry,
    BusinessToolRequest,
    BusinessToolResult,
    register_business_system_adapter,
)
from backend.app.tools.class_learning_tools import query_class_learning_summary
from backend.app.services.access_control import (
    AccessContext,
    can_access_media,
    can_manage_media,
)
from backend.app.services.authentication import resolve_access_context
from backend.app.services.audit import write_audit_log
from backend.app.services.learning import get_learning_snapshot
from backend.app.services.faq import stream_faq_answer
from backend.app.services.service_rules import stream_service_rules_answer
from backend.app.services.dependency_health import check_dependencies, overall_status
from backend.app.services.conversation_state import (
    InMemoryConversationStore,
    plan_conversation,
)


settings = get_settings()
logger = logging.getLogger(__name__)
# 只接收日志友好的追踪 ID；不允许换行或其他可造成日志注入的字符。
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
# 应用对象保持模块级单例，便于 Uvicorn 启动和测试客户端复用。实例 B 可能拿不到实例 A 中的会话状态。
app = FastAPI(title=settings.app_name, version="0.1.0")
# 开发期使用单进程内存状态；测试可通过依赖覆盖注入独立 Store。
conversation_store = InMemoryConversationStore(
    ttl_seconds=settings.conversation_ttl_seconds,
    max_entries=settings.conversation_max_entries,
)#内存会话存储
# 当前只允许本地前端开发地址；生产环境应通过配置管理允许来源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # 浏览器前端需要读取响应中的追踪 ID，便于反馈问题时提供定位线索。
    expose_headers=["X-Request-ID"],#这个 ID 主要用于：前后端联调；- 问题排查；- 日志关联；- 客服反馈故障时定位请求。
)

# 将前端页面挂载到根路径，客服演示页由 FastAPI 直接托管，避免引入额外的前端构建链路。
# 静态目录不包含密钥、数据库文件或其他内部配置。
STATIC_DIR = Path(__file__).resolve().parent / "static"

#启动检查
@app.on_event("startup")#服务启动时，根据配置决定是否检查外部依赖。
async def optional_dependency_startup_check() -> None:
    """按配置执行一次非阻断启动检查，失败时记录脱敏状态而不阻止启动。"""

    if not settings.dependency_check_on_startup:#如果配置没有开启启动检查，则直接跳过。
        return
    # 启动探针可能访问网络，放到线程中避免阻塞异步事件循环。
    dependencies = await asyncio.to_thread(check_dependencies, settings)
    logger.info("dependency_startup_health %s", json.dumps(dependencies, ensure_ascii=False))
#启动检查失败不会阻止 API 启动。这样可以避免某个非核心依赖暂时不可用时，整个服务完全无法启动。


#请求 ID 中间件
@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """为每次 HTTP 请求建立安全追踪 ID，并通过响应头返回。

    合法的上游 X-Request-ID 可以透传；非法或缺失时由服务端重新生成。
    追踪 ID 只用于链路定位，不作为认证、授权或幂等依据。
    """
    #1. 读取上游请求 ID
    incoming = request.headers.get("X-Request-ID", "")
    #2. 合法则透传，否则重新生成req_随机字符串
    request_id = (
        incoming if REQUEST_ID_PATTERN.fullmatch(incoming) else f"req_{uuid4().hex}"
    )
    #3. 写入请求上下文
    request.state.request_id = request_id
    response = await call_next(request)
    #4. 返回响应头
    response.headers["X-Request-ID"] = request_id
    return response

#媒体响应转换
def media_response(asset: MediaAsset) -> MediaAssetResponse:
    """把 ORM 媒体记录转换成不暴露对象键的公共响应。"""

    return MediaAssetResponse(
        asset_id=asset.asset_id,
        filename=asset.filename,
        media_type=asset.media_type,
        title=asset.title,
        alt_text=asset.alt_text,
        source_document=asset.source_document,
        visibility=asset.visibility,
        sha256=asset.sha256,
        size_bytes=asset.size_bytes,
        review_status=asset.review_status,
    )


def get_media_store() -> MinioMediaStore:
    """创建 MinIO 存储适配器；测试可覆盖此依赖注入假的客户端。"""

    return MinioMediaStore(settings)


def get_conversation_store() -> InMemoryConversationStore:
    """返回开发期会话存储，生产环境可在依赖层替换为持久化实现。"""

    return conversation_store


def get_intent_model():
    """按当前配置创建意图模型；未配置时由识别服务确定性降级。"""

    return build_langchain_llm(settings)


def get_a2a_learning_client() -> LocalMockA2AClient | HttpA2ALearningClient | None:
    """按功能开关和模式创建 A2A 客户端，未配置时由数据库安全兜底。"""

    if not settings.a2a_learning_enabled:
        return None
    if settings.a2a_learning_mode.lower() == "mock":
        return LocalMockA2AClient(
            max_retries=settings.a2a_learning_max_retries,
            timeout_seconds=settings.a2a_learning_timeout_seconds,
        )
    if settings.a2a_learning_mode.lower() == "local_http":
        try:
            return HttpA2ALearningClient(
                base_url=settings.a2a_learning_base_url,
                service_token=settings.a2a_learning_service_token,
                # staging 容器通过显式白名单访问 Docker 服务名；开发环境
                # 默认仍只允许本机回环地址，不能由请求参数动态修改。
                allowed_hosts={
                    host.strip()
                    for host in settings.a2a_learning_allowed_hosts.split(",")
                    if host.strip()
                },
                max_retries=settings.a2a_learning_max_retries,
                timeout_seconds=settings.a2a_learning_timeout_seconds,
            )
        except ValueError:
            # 配置错误不能阻止主 API 启动；图内会显示 A2A 失败并返回数据库摘要。
            return None
    return None


def sse_event(event: str, data: dict) -> str:
    """将一个结构化事件编码为符合 SSE 规范的文本块。

    事件数据只应包含前端确实需要的状态或回答片段。SSE 是传输格式，不是
    权限边界，因此调用方仍必须在生成事件前过滤 API Key、SQL、内部地址、
    原始学员标识和远程 Artifact 等敏感信息。
    """

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_answer(
    request: ChatRequest,
    access_context: AccessContext,
    session: Session,
    store: InMemoryConversationStore,
    intent_model=None,
    request_id: str | None = None,
    a2a_learning_client: LocalMockA2AClient | HttpA2ALearningClient | None = None,
) -> AsyncIterator[str]:
    """按阶段向客户端推送对话处理进度和最终回答。

    事件生命周期约定为 accepted → routed →（可选）a2a_task → token* →
    complete。accepted 只表示请求已接收，routed 只表示完成分流，只有
    complete 才表示本次处理已结束；前端不能把任意一个中间事件当作业务
    成功。生产环境还应补充断线重连、心跳和服务端取消机制。
    """

    # 先发送 accepted，让前端可以立即显示任务已进入处理状态。
    yield sse_event("status", {"stage": "accepted"})
    await asyncio.sleep(0)

    # 结构化识别是同步供应商调用，放到工作线程以免阻塞 SSE 事件循环。
    plan = await asyncio.to_thread(
        plan_conversation,
        request.message,
        conversation_id=request.conversation_id,
        store=store,
        model=intent_model,
    )
    route = plan.route
    # FAQ 使用独立的异步流式适配器，让真实模型片段可以直接进入 SSE。
    if route == "faq":
        yield sse_event("status", {"stage": "routed", "route": route})
        provider = "offline"
        sources = []
        async for chunk in stream_faq_answer(plan.rewritten_query):
            provider = chunk.provider
            sources = chunk.sources
            yield sse_event("token", {"content": chunk.content})
        yield sse_event(
            "complete",
            {
                "route": route,
                "provider": provider,
                # 默认不把来源信息发送到家长端；后台审计仍保留在服务内部。
                "sources": ([source.model_dump() for source in sources] if settings.expose_sources else []),
                "recognition_source": plan.recognition_source.value,
            },
        )
        return

    # 服务规则使用独立 Assistant，SSE 协议与公开咨询保持一致。
    if route == "service_rules":
        yield sse_event("status", {"stage": "routed", "route": route})
        provider = "offline"
        sources = []
        async for chunk in stream_service_rules_answer(plan.rewritten_query):
            provider = chunk.provider
            sources = chunk.sources
            yield sse_event("token", {"content": chunk.content})
        yield sse_event(
            "complete",
            {
                "route": route,
                "provider": provider,
                "sources": ([source.model_dump() for source in sources] if settings.expose_sources else []),
                "recognition_source": plan.recognition_source.value,
            },
        )
        return

    # 学情和人工分支仍通过完整 LangGraph 执行，保持数据库会话和路由契约一致。
    result = conversation_graph.invoke(
        {
            "message": request.message,
            # 意图已在入口处完成安全规划，直接写入 route，避免图内再次调用模型。
            "route": route,
            "conversation_id": request.conversation_id,
            "intent_result": plan.intent_result,
            "active_entity": plan.active_entity,
            "rewritten_query": plan.rewritten_query,
            "recognition_source": plan.recognition_source.value,
            # 追踪 ID 只在服务端状态中传播，不写入公开客服回答正文。
            "request_id": request_id,
            # 只有显式开启且依赖层成功构造客户端时，图内才尝试 A2A 增强。
            "a2a_learning_enabled": settings.a2a_learning_enabled,
            "a2a_learning_client": a2a_learning_client,
            # 身份已在 HTTP 边界完成认证。图节点只接收不可变权限上下文，
            # 不再根据请求体中的角色或用户编号自行构造身份。
            "access_context": access_context,
            "learner_id": request.learner_id,
            # 班级统计参数已由会话规划层解析为稳定的班级 ID 和日期对象。
            # 这里传递结构化值而不是把用户原文交给统计节点，避免自然语言
            # 直接影响 SQL 查询范围；统计节点仍会再次执行权限和契约校验。
            "class_id": plan.class_id,
            "class_name": plan.class_name,
            "period_start": plan.period_start,
            "period_end": plan.period_end,
            "low_balance_threshold": plan.low_balance_threshold,
            "session": session,
        },
    )
    # 路由事件用于调试和前端展示，不应包含敏感业务数据。
    yield sse_event("status", {"stage": "routed", "route": result["route"]})

    # A2A 任务事件只返回追踪字段和状态，不暴露脱敏前学员数据或 Artifact 正文。
    # 前端若需要查看报告，应使用经过授权的报告查询/下载接口，而不是把
    # 远程智能体的原始响应直接塞进 SSE。
    if result.get("a2a_status"):
        task_event = {
            "stage": "a2a_task",
            "status": result["a2a_status"],
        }
        if result.get("a2a_task_id"):
            task_event["task_id"] = result["a2a_task_id"]
        if result.get("a2a_correlation_id"):
            task_event["correlation_id"] = result["a2a_correlation_id"]
        if result["a2a_status"] != "completed":
            task_event["fallback"] = "database"
        yield sse_event("status", task_event)

    answer = result["answer"]
    # 演示阶段按字符切片模拟流式输出；生产环境可替换为模型 token 流。
    # 这能验证前端渲染和事件顺序，但不应在简历中表述为“后端已经获得
    # 真实模型逐 token 流”；真实生产链路需要处理 token 聚合、断线和背压。
    for chunk in answer:
        yield sse_event("token", {"content": chunk})
        await asyncio.sleep(0)

    yield sse_event(
        "complete",
        {
            "route": result["route"],
            "provider": result.get("provider", "database"),
            # 学情和 FAQ 都遵循来源隔离策略，避免内部字段被前端直接展示。
            "sources": ([source.model_dump() for source in result.get("sources", [])] if settings.expose_sources else []),
            "recognition_source": plan.recognition_source.value,
        },
    )


@app.get("/api/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """返回服务存活状态。"""

    return HealthResponse(status="ok", service=settings.app_name, environment=settings.app_env)


@app.get("/api/v1/health/dependencies", response_model=DependencyHealthResponse)
async def dependency_health() -> DependencyHealthResponse:
    """返回依赖状态；依赖检查放到线程中，避免阻塞异步请求循环。"""

    dependencies = await asyncio.to_thread(check_dependencies, settings)
    return DependencyHealthResponse(
        status=overall_status(dependencies),
        service=settings.app_name,
        environment=settings.app_env,
        dependencies=dependencies,
    )


@app.get("/api/v1/learners/{learner_id}/learning-snapshot", response_model=LearningSnapshotResponse)
async def learning_snapshot(
    learner_id: str,
    http_request: Request,
    actor_role: str = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> LearningSnapshotResponse:
    """返回结构化学情快照，供开发联调和未来智能体工具调用。

    响应只返回契约化摘要，不返回底层 ORM 对象。身份先由统一认证服务转换为
    AccessContext，再校验家长与学员绑定关系；正式对外时仍需由认证代理完成
    登录，并增加速率限制、查询审计和更细的字段最小化策略。
    """

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )

    snapshot = get_learning_snapshot(
        session,
        context,
        learner_id,
    )
    if snapshot is None:
        # 对外统一返回 404，避免区分“学员不存在”和“无权访问”。
        raise HTTPException(status_code=404, detail="未找到可访问的学情数据")
    return LearningSnapshotResponse.model_validate(snapshot)


@app.get(
    "/api/v1/classes/{class_id}/learning-summary",
    response_model=ClassLearningSummaryResponse,
)
async def class_learning_summary(
    class_id: str,
    http_request: Request,
    query: ClassLearningSummaryQuery = Depends(),
    session: Session = Depends(get_session),
) -> ClassLearningSummaryResponse:
    """返回授权班级的确定性学情统计。

    该接口面向教师和管理员的内部联调场景，统计指标由后端工具固定计算，
    不经过 LLM，也不允许客户端传入任意 SQL、工具名或计算公式。身份参数
    仅在 Demo 模式生效；可信 Header 模式只使用代理身份和数据库校区权限。
    """

    # 路径参数只允许作为班级查询键使用，不能改变统计范围或绕过权限判断。
    # 统计周期、阈值和身份分别来自受限的查询模型/认证上下文，避免客户端
    # 通过拼接参数注入任意查询范围。
    if not class_id or len(class_id) > 64:
        raise HTTPException(status_code=422, detail="班级编号格式无效")

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=query.actor_role,
        requested_user_id=query.actor_user_id,
    )
    try:
        summary = query_class_learning_summary(
            session,
            context,
            class_id,
            query.period_start,
            query.period_end,
            low_balance_threshold=query.low_balance_threshold,
        )
    except ValueError as exc:
        # 日期反向等业务参数错误统一转为可读的 422，而不是暴露堆栈信息。
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if summary is None:
        # 不区分“班级不存在”和“当前身份无权访问”，避免泄露班级存在性。
        raise HTTPException(status_code=404, detail="未找到可访问的班级学情数据")

    # 内部统计契约和 HTTP 响应模型虽然字段相同，但不是同一个 Pydantic 类；
    # 先转成字典再校验，避免把父类实例直接传给响应子类导致类型错误。
    return ClassLearningSummaryResponse.model_validate(summary.model_dump())


@app.post("/api/v1/media/images", response_model=MediaAssetResponse, status_code=201)
async def upload_media_image(
    http_request: Request,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=200),
    alt_text: str = Form(..., min_length=1, max_length=500),
    source_document: str = Form(..., min_length=1, max_length=300),
    visibility: MediaVisibility = Form("public_faq"),
    actor_role: ActorRole = Form("admin"),
    actor_user_id: str | None = Form(default=None, max_length=64),
    session: Session = Depends(get_session),
    store: MinioMediaStore = Depends(get_media_store),
) -> MediaAssetResponse:
    """上传图片原件并写入媒体元数据；新素材默认进入待审核状态。

    图片属于机构内容资产，可能包含教师肖像、学员作品或校区环境。对象
    存储和数据库元数据必须同时受控：先限制大小和类型，再记录来源、替代
    文本与审核状态，避免未经审核的素材直接进入公开知识库或对外展示。
    """

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )
    if not can_manage_media(context):
        raise HTTPException(status_code=403, detail="当前账号无权上传机构媒体")

    # 读取上限加一字节即可判断超限，避免无界读取大文件占满服务内存。
    content = await file.read(settings.media_max_bytes + 1)
    if len(content) > settings.media_max_bytes:
        raise HTTPException(status_code=413, detail="图片大小超过配置上限")
    try:
        summary = store.put_image(
            content,
            filename=file.filename or "upload.bin",
            media_type=file.content_type or "application/octet-stream",
            title=title,
            alt_text=alt_text,
            source_document=source_document,
            visibility=visibility,
            # 客户端不能直接把素材标记为 approved，防止绕过审核流程。
            review_status="pending",
        )
        asset = MediaAsset(**summary.model_dump())
        session.add(asset)
        write_audit_log(
            session,
            actor_user_id=context.user_id,
            action="media.upload",
            resource_type="media_asset",
            resource_id=asset.asset_id,
            outcome="success",
            metadata={"media_type": asset.media_type, "size_bytes": asset.size_bytes},
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        session.rollback()
        # 数据库写入失败时删除已上传对象，避免 MinIO 中留下不可追踪文件。
        # 这是对象存储与关系库之间的补偿动作；生产环境还应配合 outbox、
        # 定期对账和失败重试，不能把跨系统写入误当成原子事务。
        if "summary" in locals():
            try:
                store.delete_object(summary.object_key)
            except Exception:
                pass
        raise HTTPException(status_code=503, detail="媒体存储服务暂时不可用") from exc
    finally:
        await file.close()

    return media_response(asset)


@app.post("/api/v1/media/{asset_id}/review", response_model=MediaAssetResponse)
async def review_media_asset(
    asset_id: str,
    request: MediaReviewRequest,
    http_request: Request,
    actor_role: ActorRole = "admin",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
) -> MediaAssetResponse:
    """由管理员审核媒体；审核结果决定普通用户是否能获取预签名地址。"""

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )
    if context.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以审核媒体")
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="未找到媒体资产")
    asset.review_status = request.review_status
    write_audit_log(
        session,
        actor_user_id=context.user_id,
        action="media.review",
        resource_type="media_asset",
        resource_id=asset.asset_id,
        outcome="success",
        metadata={"review_status": request.review_status},
    )
    session.commit()
    return media_response(asset)


@app.get("/api/v1/media/{asset_id}/url", response_model=MediaAssetUrlResponse)
async def get_media_url(
    asset_id: str,
    http_request: Request,
    actor_role: ActorRole = "parent",
    actor_user_id: str | None = None,
    session: Session = Depends(get_session),
    store: MinioMediaStore = Depends(get_media_store),
) -> MediaAssetUrlResponse:
    """在权限和审核校验通过后生成短时 MinIO 预签名 URL。"""

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=actor_role,
        requested_user_id=actor_user_id,
    )
    asset = session.get(MediaAsset, asset_id)
    # 统一返回 404，避免通过状态码区分“资产不存在”和“无权访问”。
    if asset is None or not can_access_media(context, asset):
        raise HTTPException(status_code=404, detail="未找到可访问的媒体资产")
    try:
        url = store.create_presigned_url(asset.object_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="媒体访问服务暂时不可用") from exc
    result = media_response(asset)
    return MediaAssetUrlResponse(
        **result.model_dump(),
        url=url,
        expires_seconds=settings.minio_presigned_url_seconds,
    )


@app.post("/api/v1/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    session: Session = Depends(get_session),
    store: InMemoryConversationStore = Depends(get_conversation_store),
    intent_model=Depends(get_intent_model),
    a2a_learning_client: LocalMockA2AClient | HttpA2ALearningClient | None = Depends(get_a2a_learning_client),
) -> StreamingResponse:
    """创建一个以 SSE 格式返回的对话响应。"""

    context = resolve_access_context(
        http_request,
        session,
        settings,
        requested_role=request.actor_role,
        requested_user_id=request.actor_user_id,
    )
    # 禁止浏览器和反向代理缓存或合并事件，确保模型片段能及时到达前端。
    return StreamingResponse(
        stream_answer(
            request,
            context,
            session,
            store,
            intent_model,
            request_id=http_request.state.request_id,
            a2a_learning_client=a2a_learning_client,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def emit_safe_tool_audit(event: dict[str, str | int | float | None]) -> None:
    """输出结构化脱敏工具日志；事件契约中不包含原始问题或业务参数。"""

    logger.info("business_tool_audit %s", json.dumps(event, ensure_ascii=False))


@app.post(
    "/api/v1/internal/demo/class-availability",
    response_model=BusinessToolResult,
)
async def demo_class_availability(
    request: DemoClassAvailabilityRequest,
    http_request: Request,
) -> BusinessToolResult:
    """执行固定的只读班级名额演示，不提供任意工具名执行能力。

    接口只在 development/test/local 环境启用，返回数据明确属于演示数据。
    生产环境应替换为已认证的内部服务接口和真实 BusinessSystemsAdapter。
    """

    if settings.app_env.lower() not in {"development", "test", "local"}:
        # 生产环境表现为接口不存在，避免暴露内部演示能力。
        raise HTTPException(status_code=404, detail="接口不存在")

    adapter = FakeBusinessSystemsAdapter(
        availability={
            ("中国舞基础班", "星河中心校区"): ClassAvailabilityData(
                course_name="中国舞基础班",
                campus_name="星河中心校区",
                available_seats=3,
                schedule_options=["周六 10:00"],
                checked_at="2026-09-07T12:00:00+08:00",
            )
        }
    )
    registry = BusinessToolRegistry(audit_sink=emit_safe_tool_audit)
    register_business_system_adapter(registry, adapter=adapter)
    tool_request = BusinessToolRequest(
        tool_name="class_availability",
        course_name=request.course_name,
        campus_name=request.campus_name,
    )
    result = registry.execute(
        tool_request,
        route="schedule_or_seat",
        actor_role="demo",
        request_id=http_request.state.request_id,
    )
    if result.status == "success":
        # 用户可见信息再次强调数据范围，避免把答辩演示值误认为实时名额。
        result = result.model_copy(
            update={"message": "演示班级名额查询成功，仅用于本地测试，不代表实时名额"}
        )
    return result


# API 路由已先注册，根挂载仅负责客服演示页和静态资源。
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
