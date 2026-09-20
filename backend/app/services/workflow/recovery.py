"""启动恢复：把“跑了一半”的任务标记为 interrupted（可继续/放弃）。

手册 [A]：人工确认点必须可恢复，因此 awaiting_source_confirm / awaiting_effect_confirm
**不**在恢复范围内，重启后原样保留。
"""

from __future__ import annotations

import logging

from app.services.storage.task_store import TaskStore

logger = logging.getLogger(__name__)


def recover_on_startup(task_store: TaskStore) -> list[str]:
    marked = task_store.mark_interrupted()
    if marked:
        logger.info("启动恢复：%d 个任务被标记为 interrupted：%s", len(marked), ", ".join(marked))
    return marked
