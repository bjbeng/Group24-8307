from __future__ import annotations
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.routes import auth_routes, upload, audit, ws, rules, history
from app.routes import monitor as monitor_router


def _setup_logging() -> None:
    log_dir = Path("./data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 滚动文件：每天一个，保留 7 天
    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    # 控制台（uvicorn 也会输出，但这里保证自定义 logger 也打印）
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    # 避免重复添加
    if not root.handlers:
        root.addHandler(fh)
        root.addHandler(ch)
    else:
        root.addHandler(fh)


_setup_logging()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.upload_dir.mkdir(parents=True, exist_ok=True)

    from app.tracing.hooks import init_trace_store
    store = init_trace_store(s.engine_db_path.replace("audit.db", "traces.db"))

    from app.monitor.agent import init_monitor
    monitor = init_monitor(store, s)
    await monitor.start()

    log.info("=== Industry Audit API 启动 ===")
    yield
    monitor.stop()
    log.info("=== Industry Audit API 关闭 ===")


app = FastAPI(title="Industry Audit API", lifespan=lifespan)

s = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

app.include_router(auth_routes.router)
app.include_router(upload.router)
app.include_router(audit.router)
app.include_router(history.router)
app.include_router(ws.router)
app.include_router(rules.router)
app.include_router(monitor_router.router)

# ---------------------------------------------------------------------------
# 可选：用后端直接托管前端静态资源（用于无法启动 Vite dev server 的环境）
# - 若 ../frontend/dist 存在，则：
#   - /assets/* 由 StaticFiles 提供
#   - / 与任意前端路由都回退到 index.html
# ---------------------------------------------------------------------------
_FRONTEND_DIST = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")

    @app.get("/")
    async def frontend_index() -> FileResponse:
        return FileResponse(str(_FRONTEND_DIST / "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
