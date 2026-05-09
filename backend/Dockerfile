# ─────────────────────────────────────────────────────────
# Industry Audit Backend — Dockerfile
# 用于 Render Docker 部署
# ─────────────────────────────────────────────────────────

FROM python:3.11-slim

WORKDIR /app

# ── 系统依赖（用于编译部分原生包）───────────────────────
#RUN apt-get update && apt-get install -y --no-install-recommends \
    #build-essential \
    #&& rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── 复制后端代码 ─────────────────────────────────────────
COPY . .

# ── 安装 Python 依赖 ────────────────────────────────────
RUN pip install --no-cache-dir -e .

# ── 运行时目录（SQLite / 上传 / 日志）────────────────────
RUN mkdir -p /app/data/logs /app/data/uploads /app/data/chroma_db

# ── 端口 ─────────────────────────────────────────────────
EXPOSE 8000

# ── 启动 ─────────────────────────────────────────────────
# Render 会自动注入 PORT 环境变量
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
