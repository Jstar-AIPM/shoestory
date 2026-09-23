"""FastAPI 入口：/api/v1 接口 + 静态最小验收界面。

启动：`python -m uvicorn app.main:app --host 0.0.0.0 --port 8787`（在 backend/ 目录下执行）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1 import admin as admin_router
from app.api.v1 import archive as archive_router
from app.api.v1 import inspect as inspect_router
from app.api.v1 import auth as auth_router
from app.api.v1 import system as system_router
from app.api.v1 import tasks as tasks_router
from app.core.config import Settings
from app.core.container import build_container
from app.core.errors import AppError, ErrorCode, message_for
from app.core.logging import log_jsonl_path, log_event, setup_logging
from app.services.prompts.loader import prompt_inventory
from app.services.workflow.recovery import recover_on_startup

logger = logging.getLogger("app")

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
        # 首次启动把环境变量里的初始邀请码落到存储（已存在则跳过）
        bootstrapped = container.invite_store.bootstrap_from_env()
        if bootstrapped:
            logger.info("已从环境变量初始化 %d 个邀请码（不打印码本身）", len(bootstrapped))
        # 启动自检：Prompt 模板是运行时必需资源，缺了就是"部署包不完整"，必须立刻可见
        missing_files = [name for name, ok in prompt_inventory().items() if not ok]
        if missing_files:
            logger.error(
                "启动自检失败：缺少 %d 个 Prompt 文件 %s（检查部署打包规则是否排除了 prompts/*.md）",
                len(missing_files),
                ", ".join(missing_files),
            )
        log_event(
            logger,
            "startup",
            env=settings.env,
            storage=settings.storage_provider,
            provider_mode=container.providers.mode,
            interrupted_tasks=len(marked),
            data_root=str(settings.data_root),
            log_path=str(log_jsonl_path() or ""),
            missing_prompts=missing_files,
            warmup_urls=[urlsplit(u).netloc for u in container.warmup.urls],
        )
        # 自预热：让网关到本实例的长连接不因空闲失效（详见 services/warmup.py）
        container.warmup.start()
        yield
        container.warmup.stop()
        container.runner.shutdown()
        log_event(logger, "shutdown")

    app = FastAPI(
        title="鞋历 · 鞋柜线稿 Agent",
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
    app.include_router(inspect_router.router, prefix="/api/v1")
    app.include_router(tasks_router.router, prefix="/api/v1")
    app.include_router(archive_router.router, prefix="/api/v1")
    app.include_router(auth_router.router, prefix="/api/v1")
    app.include_router(admin_router.router, prefix="/api/v1")

    return app


app = create_app()
