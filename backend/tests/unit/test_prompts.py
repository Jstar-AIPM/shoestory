"""Prompt 与部署打包的自检（阶段 4 线上事故复盘后新增）。

事故：`backend/.vefaasignore` 里的 `*.md` 把 `app/services/prompts/*.md` 排除出代码包，
线上模型只拿到兜底提示词 → 输出结构校验失败 → 「点了生成没反应」，日志里却看不到原因。

本文件把两类"会静默失败"的问题变成测试失败：
1. Prompt 文件缺失/为空，或 Prompt 与 schema 字段不一致；
2. 打包排除清单（.vefaasignore）误伤运行时必需资源（prompts/*.md、styles/*.yaml）。
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from app.core.config import PROMPTS_DIR, REPO_ROOT
from app.schemas.llm import ModelResolveOut, QualityReportOut
from app.services.prompts import loader

# ---------------- 1. Prompt 文件本身 ----------------

@pytest.mark.parametrize("name", loader.REQUIRED_PROMPTS)
def test_required_prompt_exists_and_not_empty(name: str) -> None:
    path = PROMPTS_DIR / name
    assert path.is_file(), f"必需 Prompt 缺失：{path}"
    assert len(path.read_text(encoding="utf-8").strip()) > 50, f"Prompt 内容过短，疑似占位：{path}"


def test_resolve_prompt_mentions_every_schema_field() -> None:
    """提示词必须把 schema 里的字段写清楚，否则模型会返回形状不对的 JSON。"""
    text = (PROMPTS_DIR / "resolve_model.md").read_text(encoding="utf-8")
    for field in ModelResolveOut.model_fields:
        assert field in text, f"resolve_model.md 未提及字段 {field}"


def test_verify_prompt_mentions_every_quality_dimension() -> None:
    text = (PROMPTS_DIR / "verify_lineart.md").read_text(encoding="utf-8")
    for field in QualityReportOut.model_fields:
        assert field in text, f"verify_lineart.md 未提及字段 {field}"


def test_prompts_ready_reports_true_in_repo() -> None:
    assert loader.prompts_ready() is True
    assert all(loader.prompt_inventory().values())


# ---------------- 2. 加载器行为：缺失必须"记账"，不许静默 ----------------

def test_missing_prompt_returns_fallback_and_is_recorded(caplog: pytest.LogCaptureFixture) -> None:
    loader.reset_missing()
    with caplog.at_level("ERROR"):
        text = loader.load_prompt_text("no-such-prompt.md", fallback="FALLBACK")
    assert text == "FALLBACK"
    assert "no-such-prompt.md" in loader.missing_prompts(), "缺失的 Prompt 必须进入缺失清单（健康检查会读）"
    assert any("Prompt 文件读不到" in r.getMessage() for r in caplog.records), "缺失必须记 ERROR 日志"

    # 正常情况下不应记账；已有记录也不影响其他文件
    loader.load_prompt_text("resolve_model.md")
    assert loader.missing_prompts() == ["no-such-prompt.md"]
    loader.reset_missing()
    assert loader.missing_prompts() == []


def test_provider_prompts_are_loaded_from_files(settings) -> None:
    """真实 provider 拿到的 system_prompt 必须是文件内容，而不是兜底句。"""
    from app.services.providers.ark_text import SYSTEM_FALLBACK as TEXT_FALLBACK
    from app.services.providers.ark_text import ArkModelResolver
    from app.services.providers.ark_vision import SCREEN_FALLBACK
    from app.services.providers.ark_vision import SYSTEM_FALLBACK as VISION_FALLBACK
    from app.services.providers.ark_vision import ArkQualityJudge

    assert ArkModelResolver(settings).system_prompt != TEXT_FALLBACK
    judge = ArkQualityJudge(settings)
    assert judge.system_prompt != VISION_FALLBACK
    # 预筛提示词走另一个加载函数：这里必须显式验证脚本化，
    # 否则一旦打包漏了 prompt，只有线上真跑搜图时才会以 500 暴露（已踩过）。
    assert judge._load_screen_prompt() != SCREEN_FALLBACK


def test_every_runtime_prompt_used_by_code_is_in_required_list() -> None:
    """代码里实际读的 Prompt 文件名，必须在 REQUIRED_PROMPTS 里（否则健康检查会漏报）。"""
    sources = list((REPO_ROOT / "backend" / "app").rglob("*.py"))
    referenced: set[str] = set()
    for path in sources:
        text = path.read_text(encoding="utf-8")
        referenced.update(re.findall(r'load_prompt_text\(\s*"([^"]+\.md)"', text))
    assert referenced, "没有找到任何 load_prompt_text 调用，测试已失效"
    missing = referenced - set(loader.REQUIRED_PROMPTS)
    assert not missing, f"这些 Prompt 被代码读取但不在 REQUIRED_PROMPTS 里：{sorted(missing)}"


# ---------------- 3. 打包规则的回归护栏 ----------------

def _ignore_patterns(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _matches(pattern: str, relative: str) -> bool:
    """近似 gitignore 语义的匹配（足够覆盖本项目用到的规则形态）。

    关键差异：
    - 不含斜杠的模式（如 `*.md`）匹配**任意层级**；
    - 带前导斜杠或内部斜杠的模式（如 `/*.md`、`docs/`）**锚定根目录**，
      所以 `/*.md` 只排除顶层 md，不会误伤 `app/services/prompts/*.md`。
    """
    raw = pattern[1:] if pattern.startswith("!") else pattern
    is_dir_rule = raw.endswith("/")
    anchored = raw.startswith("/") or "/" in raw.rstrip("/")
    clean = raw.strip("/")

    if is_dir_rule:
        if anchored:
            return relative == clean or relative.startswith(clean + "/")
        return f"/{relative}/" .count(f"/{clean}/") > 0 or relative.startswith(clean + "/")
    if anchored:
        if "/" in clean:
            return fnmatch.fnmatch(relative, clean)
        return "/" not in relative and fnmatch.fnmatch(relative, clean)
    return fnmatch.fnmatch(Path(relative).name, clean)


def _would_be_excluded(patterns: list[str], relative: str) -> bool:
    """按顺序应用规则，后匹配的规则覆盖先匹配的（支持 `!` 取反）。"""
    excluded = False
    for pattern in patterns:
        if _matches(pattern, relative):
            excluded = not pattern.startswith("!")
    return excluded


RUNTIME_ASSETS = [
    "app/services/prompts/resolve_model.md",
    "app/services/prompts/verify_lineart.md",
    "app/services/prompts/rank_source_images.md",
    "app/services/prompts/screen_source_images.md",
    "app/services/prompts/styles/bw_lineart.yaml",
]


@pytest.mark.parametrize("relative", RUNTIME_ASSETS)
def test_vefaasignore_keeps_runtime_assets(relative: str) -> None:
    """打包排除清单绝不能把 Prompt / 风格模板排除掉（2026-09-21 线上事故的直接护栏）。"""
    ignore = Path(__file__).resolve().parents[2] / ".vefaasignore"
    assert ignore.is_file(), f"缺少打包排除清单：{ignore}"
    patterns = _ignore_patterns(ignore)
    assert not _would_be_excluded(patterns, relative), (
        f"{relative} 会被 .vefaasignore 排除出代码包 → 线上必然失败。请修正排除规则。"
    )


def test_vefaasignore_still_excludes_secrets_and_tests() -> None:
    """排除规则要保留：密钥文件与测试不能被上传。"""
    ignore = Path(__file__).resolve().parents[2] / ".vefaasignore"
    patterns = _ignore_patterns(ignore)
    for relative in (".env", "tests/unit/test_prompts.py", ".venv/lib/python3.12/site.py"):
        assert _would_be_excluded(patterns, relative), f"{relative} 未被排除，存在泄露/膨胀风险"


def test_repo_root_ignore_does_not_hit_backend_prompts() -> None:
    """仓库根目录那份排除清单（备用部署路径）也不能误伤 Prompt。"""
    ignore = REPO_ROOT / ".vefaasignore"
    if not ignore.is_file():  # pragma: no cover - 根清单总是存在
        pytest.skip("根目录没有 .vefaasignore")
    patterns = _ignore_patterns(ignore)
    for relative in ("backend/app/services/prompts/resolve_model.md",):
        assert not _would_be_excluded(patterns, relative)


def test_verify_prompt_judges_logo_against_what_is_visible() -> None:
    """规则钉死（2026-09-23 线上误杀后加的）：Logo 只按"参考图里看得见的"判。

    AJ36 那次，照片角度看不到飞人 Logo，却被扣 logo_legibility/logo_filled → 整单失败、白烧两次生成。
    """
    text = (PROMPTS_DIR / "verify_lineart.md").read_text(encoding="utf-8")
    assert "图1 里实际看得见的" in text
    assert "看不到标识时给 1.0" in text
    assert "不要因为" in text and "飞人" in text
