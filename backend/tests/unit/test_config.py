"""配置健壮性：`.env` 必须能直接加载（含空值与行内注释习惯）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import REPO_ROOT, Settings
from app.core.container import build_container
from app.core.errors import AppError, ErrorCode

ENV_EXAMPLE = REPO_ROOT / ".env.example"


def test_env_example_is_loadable() -> None:
    """交付给产品经理的 .env.example 必须能直接复制使用（不报解析错误）。"""
    settings = Settings(_env_file=str(ENV_EXAMPLE))
    assert settings.app_port == 8787
    assert settings.storage_provider == "local"
    assert settings.global_daily_generate_limit is None  # 空值 = 不限制
    assert settings.use_mock_providers is True  # 没配 Key -> 演示模式


def test_blank_optional_number_means_unset() -> None:
    assert Settings(_env_file=None, global_daily_generate_limit="").global_daily_generate_limit is None
    assert Settings(_env_file=None, global_daily_generate_limit="  ").global_daily_generate_limit is None
    assert Settings(_env_file=None, global_daily_generate_limit="30").global_daily_generate_limit == 30


def test_mock_mode_switches_off_when_key_present() -> None:
    full = {
        "ark_api_key": "k",
        "ark_text_model": "ep-text",
        "ark_vision_model": "ep-vision",
        "ark_image_model": "ep-image",
    }
    assert Settings(_env_file=None, **full).use_mock_providers is False
    assert Settings(_env_file=None, **full).real_mode_ready is True
    # 有 Key 但显式强制 mock（开发/测试用）
    forced = Settings(_env_file=None, force_mock_provider=True, **full)
    assert forced.use_mock_providers is True
    # 无 Key 且关闭 mock 兜底 -> 如实走真实路径并报缺 Key（不假装成功）
    strict = Settings(_env_file=None, ark_api_key="", enable_mock_provider=False)
    assert strict.use_mock_providers is False


def test_partial_config_falls_back_to_mock_with_clear_hint() -> None:
    """只填了 API Key、还没填模型时：服务不应崩，退回演示模式并说清缺什么。"""
    partial = Settings(_env_file=None, ark_api_key="only-key")
    assert partial.missing_ark_config == [
        "ARK_TEXT_MODEL",
        "ARK_VISION_MODEL",
        "ARK_IMAGE_MODEL",
    ]
    assert partial.use_mock_providers is True
    assert partial.real_mode_ready is False

    container = build_container(partial)
    assert container.providers.mode == "mock"
    assert "ARK_TEXT_MODEL" in container.providers.missing
    assert any("还缺配置" in note for note in container.notes)

    # 明确关掉 mock 兜底时，才应该直接报配置不完整
    strict = Settings(_env_file=None, ark_api_key="only-key", enable_mock_provider=False)
    with pytest.raises(AppError) as excinfo:
        build_container(strict)
    assert excinfo.value.code is ErrorCode.UPSTREAM_AUTH_FAILED


def test_data_root_is_resolved_against_repo_root() -> None:
    settings = Settings(_env_file=None, data_dir="./data")
    assert settings.data_root.is_absolute()
    assert settings.data_root.name == "data"


def test_redaction_covers_all_secrets() -> None:
    settings = Settings(
        _env_file=None,
        ark_api_key="ARK-SECRET",
        volc_search_api_key="SEARCH-SECRET",
        volc_accesskey="AK-SECRET",
        volc_secretkey="SK-SECRET",
        invite_codes="CODE-SECRET",
        admin_code="ADMIN-SECRET",
    )
    values = settings.redaction_values()
    for secret in ("ARK-SECRET", "SEARCH-SECRET", "AK-SECRET", "SK-SECRET", "CODE-SECRET", "ADMIN-SECRET"):
        assert secret in values


def test_env_example_has_no_inline_comments_on_values() -> None:
    """行内注释会被当成取值（踩过一次），这里锁死这个约束。"""
    for raw in Path(ENV_EXAMPLE).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1]
        assert "#" not in value, f"这一行的取值里带了 # 注释，会解析失败：{line}"
