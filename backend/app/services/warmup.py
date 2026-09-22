"""自预热（keep-warm）：让云端实例与网关之间的连接不因空闲而失效。

## 为什么需要它（2026-09-22 线上实测复盘）

线上是 veFaaS 弹性实例 + API 网关。实例空闲一段时间后：

- 实例本身还在（`vefaas fn instances` 显示同一实例、状态 Ready）；
- 但**网关到实例的那条长连接会先失效** —— 于是「空闲后的第一个请求」会长时间无响应
  （实测 60s、180s 都出现过，**浏览器打开首页也会 `ERR_TIMED_OUT`**），
  紧接着的第二个请求只需 0.2s。

这类问题的官方解法是**预留实例**（常驻实例、消除冷启动），但预留实例按时间计费 ——
在"省钱优先"的前提下我们改用更轻的折中：**进程内按固定间隔请求自己的公网地址**，
让网关侧连接始终保持活跃。

## 取舍（诚实记录，不假装这等于预留实例）

- 好处：几乎零成本；实测能消除"空闲后第一个请求卡住"。
- 局限：进程被彻底销毁时它不会运行（靠 veFaaS 定时触发器把进程叫醒，我们再接力去焐网关连接）；
  极端情况下（定时器与自预热都被中断）仍可能出现一次慢请求，此时前端的"服务正在启动，请稍等几秒"
  文案与幂等 GET 自动重试会接住。
- 间隔不能太短：默认 180 秒，与定时触发器同频即可，避免无意义的调用量。
"""

from __future__ import annotations

import logging
import threading
from urllib.parse import urlsplit

import httpx

from app.core.logging import log_event

logger = logging.getLogger("app.warmup")


class WarmupLoop:
    """按间隔 GET 指定 URL 的守护线程（只做预热，不影响业务）。"""

    def __init__(
        self,
        urls: list[str],
        *,
        interval_seconds: int = 180,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.urls = [u.strip() for u in urls if u and u.strip()]
        self.interval = max(30, interval_seconds)
        self.timeout = max(3.0, timeout_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 生命周期
    @property
    def enabled(self) -> bool:
        return bool(self.urls)

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="lvli-warmup", daemon=True)
        self._thread.start()
        log_event(
            logger,
            "warmup_started",
            urls=[urlsplit(u).netloc for u in self.urls],
            interval_seconds=self.interval,
        )

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    # ------------------------------------------------------------------ 工作
    def _run(self) -> None:
        # 先等一个间隔再开始：启动瞬间本来就有请求（避免无意义开销）
        while not self._stop.wait(self.interval):
            self.ping_once()

    def ping_once(self) -> list[tuple[str, bool, str]]:
        """对所有 URL 各发一次 GET（短超时；失败只记日志，绝不抛出）。"""
        results: list[tuple[str, bool, str]] = []
        for url in self.urls:
            try:
                response = httpx.get(url, timeout=self.timeout, follow_redirects=False)
                ok = response.status_code < 500
                results.append((url, ok, f"HTTP {response.status_code}"))
                log_event(
                    logger,
                    "warmup_ping",
                    target=urlsplit(url).netloc,
                    path=urlsplit(url).path or "/",
                    status=response.status_code,
                    ok=ok,
                )
            except Exception as exc:  # noqa: BLE001 - 预热失败不影响任何业务
                results.append((url, False, type(exc).__name__))
                log_event(
                    logger,
                    "warmup_ping",
                    target=urlsplit(url).netloc,
                    path=urlsplit(url).path or "/",
                    status=None,
                    ok=False,
                    error=type(exc).__name__,
                )
        return results

    # 供测试与手动诊断使用：等待线程真正退出
    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
