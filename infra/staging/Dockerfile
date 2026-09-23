# uPil staging 镜像使用多阶段构建：Node 阶段只负责编译 Vue SPA，
# Python 阶段只保留静态产物和 API 运行时，不携带 node_modules 或前端源码。
FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

# 先复制锁文件并使用 npm ci，保证 CI、开发机和镜像构建使用同一依赖图。
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Vue 构建不读取真实服务端环境；浏览器只使用同源 /api 路径。
COPY frontend ./
RUN npm run build


# Python 运行阶段保持项目约定的 3.11 基线。
# 该镜像只包含应用运行所需内容，不安装 Docker CLI，也不挂载 Docker Socket。
FROM python:3.11-slim AS runtime

# 关闭 Python 字节码文件和缓冲输出，便于容器日志被实时采集。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint 依赖 Pango、Cairo 和字体配置；Noto CJK 保证中文报告不会
# 静默回退为缺字字体。安装后删除 apt 索引，避免把缓存留在运行镜像中。
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-noto-cjk \
        fontconfig \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 运行用户，降低应用进程发生越权后的影响范围。
RUN groupadd --system --gid 10001 upil \
    && useradd --system --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin upil

WORKDIR /app

# 先复制依赖描述文件，利用 Docker 构建缓存减少源码变更后的重复安装。
COPY pyproject.toml README.md ./

# 先放入 Python 包源码；否则 setuptools 无法发现 backend 包。
COPY backend ./backend

# 用前端构建阶段的 dist 替换源码树中的旧演示静态页。这样本地源码仍可
# 保留回退参考，最终镜像则只由 FastAPI 同源托管经过验证的 Vue 产物。
RUN rm -rf ./backend/app/static
COPY --from=frontend-builder /app/frontend/dist ./backend/app/static

# 安装项目依赖、storage 和 memory extra，使报告 MinIO 适配器与 Redis
# 短期会话后端都可按配置启用。
# 不安装 dev extra；pytest 在宿主机或专用 CI 镜像中执行。
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[storage,memory]"

# 将应用目录交给非 root 用户，保证运行时不会产生 root 所属文件。
RUN chown -R upil:upil /app
USER upil

# API 容器内端口；对宿主机的实际暴露由 Compose 文件控制。
EXPOSE 8000

# 使用 exec 形式，让 Uvicorn 能正确接收容器停止信号。
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# 可选测试阶段复用与 runtime 完全相同的 Linux 原生库和中文字体，只在
# 显式构建 --target report-tests 时安装 pytest、复制测试源码并运行真实渲染。
# staging 最终运行镜像仍停留在 runtime，不包含测试依赖或测试数据。
FROM runtime AS report-tests

USER root
RUN python -m pip install ".[dev]"
COPY tests ./tests
# pytest 的统一 basetemp 位于项目根目录。镜像构建时预先创建并授权，保证
# 专项测试仍以非 root 身份运行，也能安全创建临时数据库和子目录。
RUN mkdir -p /app/.test-artifacts/pytest \
    && chown -R upil:upil /app/tests /app/.test-artifacts
USER upil
ENV UPIL_REQUIRE_PDF_RUNTIME=true

# 专项测试在该环境变量下会把原生库或字体缺失从 skip 提升为失败，确保
# 家长和教师 PDF 都真实经过 WeasyPrint、Pango、Cairo、Noto CJK 和 pypdf。
RUN python -m pytest tests/test_report_pdf.py tests/test_class_report_pdf.py -q -rs


# Docker 未指定 target 时会使用最后一个阶段。显式回到纯 runtime，避免默认
# staging 镜像携带 pytest 和测试源码；report-tests 仍可按名称单独构建。
FROM runtime AS final
