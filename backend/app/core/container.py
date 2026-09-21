"""依赖容器：把配置、存储、风格、上游提供方、执行器装配在一起。

测试通过 `build_container(临时 settings)` 得到完全隔离的实例（不碰真实 data/）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import STYLES_DIR, Settings
from app.services.auth.invite_store import InviteStore
from app.services.auth.session import SessionSigner
from app.services.providers.base import ProviderBundle, build_providers
from app.services.storage.archive_store import ArchiveStore
from app.services.storage.asset_store import AssetStore
from app.services.storage.backend import StorageBackend, build_backend
from app.services.storage.task_store import TaskStore
from app.services.style.registry import StyleRegistry
from app.services.workflow.runner import PipelineRunner


@dataclass
class Container:
    settings: Settings
    backend: StorageBackend
    styles: StyleRegistry
    providers: ProviderBundle
    archive_store: ArchiveStore
    task_store: TaskStore
    asset_store: AssetStore
    runner: PipelineRunner
    invite_store: InviteStore
    session_signer: SessionSigner
    notes: list[str] = field(default_factory=list)

    @property
    def provider_mode(self) -> str:
        return self.providers.mode


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    backend = build_backend(settings)
    styles = StyleRegistry(STYLES_DIR)
    providers = build_providers(settings)
    archive_store = ArchiveStore(backend)
    task_store = TaskStore(backend)
    asset_store = AssetStore(backend)
    invite_store = InviteStore(backend, settings)
    session_signer = SessionSigner(backend, settings)
    runner = PipelineRunner(
        settings=settings,
        backend=backend,
        task_store=task_store,
        asset_store=asset_store,
        providers=providers,
        styles=styles,
    )
    notes: list[str] = []
    if providers.mode == "mock":
        if providers.missing:
            notes.append(
                "演示模式（mock 上游）：还缺配置 "
                + "、".join(providers.missing)
                + "，补齐后重启即切换到真实模型"
            )
        else:
            notes.append("演示模式（mock 上游）：已强制走 mock（FORCE_MOCK_PROVIDER=true）")
    if providers.search.mode == "mock" and providers.mode == "real":
        notes.append("搜图走 mock：未配置豆包搜索凭证")
    if settings.storage_provider != "local":
        notes.append(f"存储后端：{settings.storage_provider}")
    if settings.auth_required:
        notes.append("已启用邀请码登录：未持有效会话的请求将被拒绝（401）")
    return Container(
        settings=settings,
        backend=backend,
        styles=styles,
        providers=providers,
        archive_store=archive_store,
        task_store=task_store,
        asset_store=asset_store,
        runner=runner,
        invite_store=invite_store,
        session_signer=session_signer,
        notes=notes,
    )
