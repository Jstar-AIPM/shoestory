"""`date_text` 解析规则（纯函数，重点单测）—— 对应阶段文档 6.3 表格。"""

from __future__ import annotations

import pytest

from app.services.datetext import parse_date_text


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
