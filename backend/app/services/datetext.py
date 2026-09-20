"""`date_text` -> `date_sort_key` 解析（纯函数，重点单测）。

规则见《第 1 阶段技术开发文档》6.3：
- `2021` -> 2021-01-01；`2021-06` / `2021年6月` -> 2021-06-01；`2021-06-15` -> 精确
- `2019-2021` / `2019–2021` / `2019~2021` -> 取起始年
- 无法解析（如“高三那年”）-> None（排在最后），不报错，只记录 failed 标记
- 全角转半角、去空白；非法月份/日期视为不可解析
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_FULLWIDTH = str.maketrans(
    {
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "－": "-", "―": "-", "—": "-", "–": "-", "﹣": "-",
        "／": "/", "．": ".", "～": "~", "　": " ",
    }
)

_YMD = re.compile(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$")
_YM = re.compile(r"^(\d{4})[-/.年](\d{1,2})月?$")
_YEAR = re.compile(r"^(\d{4})年?$")
_RANGE_SPLIT = re.compile(r"^\s*(.+?)\s*[-~至到]+\s*(.+?)\s*$")


@dataclass(frozen=True)
class DateParseResult:
    key: str | None
    failed: bool = False
    kind: str = "empty"

    @property
    def parsed(self) -> bool:
        return self.key is not None


def normalize(text: str) -> str:
    return text.translate(_FULLWIDTH).replace(" ", "").strip()


def _build(year: int, month: int = 1, day: int = 1) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _parse_single(text: str) -> DateParseResult:
    match = _YMD.match(text)
    if match:
        year, month, day = (int(g) for g in match.groups())
        key = _build(year, month, day)
        return DateParseResult(key, failed=key is None, kind="ymd")
    match = _YM.match(text)
    if match:
        year, month = (int(g) for g in match.groups())
        key = _build(year, month)
        return DateParseResult(key, failed=key is None, kind="ym")
    match = _YEAR.match(text)
    if match:
        year = int(match.group(1))
        key = _build(year)
        return DateParseResult(key, failed=key is None, kind="year")
    return DateParseResult(None, failed=True, kind="unparsed")


def parse_date_text(text: str | None) -> DateParseResult:
    """把自由文本日期解析成可排序的 `YYYY-MM-DD`（无法解析返回 None）。"""
    if text is None:
        return DateParseResult(None, failed=False, kind="empty")
    normalized = normalize(str(text))
    if not normalized:
        return DateParseResult(None, failed=False, kind="empty")

    # 先按单值解析：避免 `2021-06` 被误判成“区间”
    single = _parse_single(normalized)
    if single.parsed:
        return single
    if single.kind != "unparsed":
        # 形如年月/年月日但日历值非法（如 2021-13）-> 直接算解析失败，不再当区间
        return single

    # 再试区间：`2019-2021` / `2019年6月-2021年9月` -> 取起始
    match = _RANGE_SPLIT.match(normalized)
    if match:
        left = _parse_single(match.group(1))
        if left.parsed:
            return DateParseResult(left.key, failed=False, kind="range")
        right = _parse_single(match.group(2))
        if right.parsed:
            return DateParseResult(right.key, failed=False, kind="range")

    return single
