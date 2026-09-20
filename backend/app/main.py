"""FastAPI 入口：/api/v1 接口 + 静态最小验收界面。

启动：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8787`（在 backend/ 目录下执行）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import archive as archive_router
from app.api.v1 import system as system_router
from app.api.v1 import tasks as tasks_router
from app.core.config import Settings
from app.core.container import build_container
from app.core.errors import AppError, ErrorCode, message_for
from app.core.logging import log_jsonl_path, log_event, setup_logging
from app.services.workflow.recovery import recover_on_startup

logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_root.mkdir(parents=True, exist_ok=True)
    setup_logging(
        settings.data_root / "logs" / "app.jsonl",
        level=settings.app_log_level,
        secrets=settings.redaction_values(),
    )
    container = build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动恢复：跑了一半的任务标记为 interrupted（人工确认点保留）
        marked = recover_on_startup(container.task_store)
        log_event(
            logger,
            "startup",
            env=settings.env,
            storage=settings.storage_provider,
            provider_mode=container.providers.mode,
            interrupted_tasks=len(marked),
            data_root=str(settings.data_root),
            log_path=str(log_jsonl_path() or ""),
        )
        yield
        container.runner.shutdown()
        log_event(logger, "shutdown")

    app = FastAPI(
        title="履历 · 鞋柜线稿 Agent（阶段 1）",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.container = container

    # ---------------- 统一错误处理（不泄露堆栈） ----------------
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        log_event(logger, "app_error", code=exc.code.value, detail=exc.detail)
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = {"fields": [{"loc": ".".join(str(p) for p in e.get("loc", ())), "type": e.get("type")} for e in exc.errors()[:5]]}
        return JSONResponse(
            status_code=422,
            content={"error": {"code": ErrorCode.INVALID_INPUT.value, "message": message_for(ErrorCode.INVALID_INPUT), "detail": detail}},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": message_for(ErrorCode.INTERNAL_ERROR),
                }
            },
        )

    # ---------------- 路由 ----------------
    app.include_router(system_router.router, prefix="/api/v1")
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.include_router(archive_router.router, prefix="/api/v1")
    # 阶段 4：app.include_router(auth_router.router, prefix="/api/v1")  # 邀请码登录

    # ---------------- 最小验收界面（单 HTML，无构建） ----------------
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "accept.html")

    return app


app = create_app()
