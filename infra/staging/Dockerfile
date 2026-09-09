# uPil staging 镜像：使用 Python 3.11，和项目约定的运行时基线保持一致。
# 该镜像只包含应用运行所需内容，不安装 Docker CLI，也不挂载 Docker Socket。
FROM python:3.11-slim

# 关闭 Python 字节码文件和缓冲输出，便于容器日志被实时采集。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 创建非 root 运行用户，降低应用进程发生越权后的影响范围。
RUN groupadd --system --gid 10001 upil \
    && useradd --system --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin upil

WORKDIR /app

# 先复制依赖描述文件，利用 Docker 构建缓存减少源码变更后的重复安装。
COPY pyproject.toml README.md ./

# 先放入 Python 包源码；否则 setuptools 无法发现 backend 包。
COPY backend ./backend

# 安装项目依赖和 media extra，使 MinIO 适配器在 staging 中可按配置启用。
# 不安装 dev extra；pytest 在宿主机或专用 CI 镜像中执行。
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[media]"

# 将应用目录交给非 root 用户，保证运行时不会产生 root 所属文件。
RUN chown -R upil:upil /app
USER upil

# API 容器内端口；对宿主机的实际暴露由 Compose 文件控制。
EXPOSE 8000

# 使用 exec 形式，让 Uvicorn 能正确接收容器停止信号。
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
