"""`date_text` 解析规则（纯函数，重点单测）—— 边界与歧义优先。"""

from __future__ import annotations

import pytest

from app.services.datetext import human_hint, parse_date_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2021", "2021-01-01"),
        ("2021年", "2021-01-01"),
        ("2021-06", "2021-06-01"),
        ("2021/6", "2021-06-01"),
        ("2021年6月", "2021-06-01"),
        ("2021.6", "2021-06-01"),
        ("2021-06-15", "2021-06-15"),
        ("2021/6/15", "2021-06-15"),
        ("2021年6月15日", "2021-06-15"),
        ("2021.6.15", "2021-06-15"),
        # 区间：4 位 - 4 位 取起始年
        ("2019-2021", "2019-01-01"),
        ("2019–2021", "2019-01-01"),
        ("2019~2021", "2019-01-01"),
        ("2019年—2021年", "2019-01-01"),
        ("2021年6月-2021年9月", "2021-06-01"),
        # 全角/空格容错
        ("２０２１年６月", "2021-06-01"),
        ("  2021 年 6 月  ", "2021-06-01"),
    ],
)
def test_parse_ok(text: str, expected: str) -> None:
    result = parse_date_text(text)
    assert result.key == expected
    assert result.failed is False


@pytest.mark.parametrize("text", ["高三那年", "大学时期", "刚工作的时候", "很久以前", "abc"])
def test_parse_unparsed_returns_none(text: str) -> None:
    result = parse_date_text(text)
    assert result.key is None
    assert result.failed is True


@pytest.mark.parametrize("text", [None, "", "   "])
def test_parse_empty(text) -> None:
    result = parse_date_text(text)
    assert result.key is None
    assert result.failed is False  # 空值不算解析失败
    assert result.kind == "empty"


@pytest.mark.parametrize("text", ["2021-13", "2021年13月", "2021-02-30", "2021年2月30日"])
def test_parse_invalid_calendar_values(text: str) -> None:
    result = parse_date_text(text)
    assert result.key is None
    assert result.failed is True


def test_range_kind_is_recorded() -> None:
    assert parse_date_text("2019-2021").kind == "range"
    assert parse_date_text("2021年6月").kind == "ym"
    assert parse_date_text("2021").kind == "year"
    assert parse_date_text("2021-06-15").kind == "ymd"


# ---------------- 给界面看的人话提示（不露排序键） ----------------
# 产品反馈（2026-09-23）：界面上不该出现 2021-06-01 这种机械键值。


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2021", "识别为 2021年"),
        ("2021年6月", "识别为 2021年6月"),
        ("2021-06", "识别为 2021年6月"),
        ("2021-06-15", "识别为 2021年6月15日"),
        ("2019–2021", "识别为 2019 年起"),
        ("", "留空即可，之后也能补"),
    ],
)
def test_human_hint_reads_like_a_sentence(text: str, expected: str) -> None:
    assert human_hint(parse_date_text(text)) == expected


def test_human_hint_hides_sort_key_and_explains_failure() -> None:
    hint = human_hint(parse_date_text("2021年6月"))
    assert "2021-06-01" not in hint, "提示里不得出现排序键"

    failed = human_hint(parse_date_text("高三那年"))
    assert "没看懂" in failed
    assert "2021" in failed, "失败时要给出可操作的写法示例"
