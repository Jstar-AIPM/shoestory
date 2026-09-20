"""日志脱敏：密钥不入日志，用户故事只记长度。"""

from __future__ import annotations

import logging

from app.core.logging import log_event, setup_logging

SECRET = "sk-test-DEADBEEF-1234567890"
STORY = "这是不能落盘的私人故事原文"


def test_secret_and_story_are_not_written(tmp_path) -> None:
    log_path = tmp_path / "logs" / "app.jsonl"
    setup_logging(log_path, level="INFO", secrets=[SECRET])
    logger = logging.getLogger("test.redaction")

    log_event(logger, "upstream_call", key=SECRET, note=f"使用 {SECRET} 调用模型", story=STORY)
    logger.info("直接打印 %s", SECRET)

    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_path.read_text(encoding="utf-8")

    assert SECRET not in content
    assert "***" in content
    assert STORY not in content
    assert f'"story_len": {len(STORY)}' in content


def test_redact_helper_replaces_all_occurrences(tmp_path) -> None:
    from app.core.logging import redact

    setup_logging(tmp_path / "app.jsonl", level="INFO", secrets=[SECRET])
    assert redact(f"a{SECRET}b{SECRET}") == "a***b***"
    assert redact("普通文本") == "普通文本"
