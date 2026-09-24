"""选最优稿（services/tools/select_artwork.py）的单元测试。

锁住线上那个很难发现的错误：**用户归档到的是质检明确判过不合格的那张稿子。**
Nike Air Force 1 生成过两次，分数完全相同（0.9525），但第 1 次 `passed=False`（勾没填）、
第 2 次 `passed=True`。原来的 `max(key=score)` 同分时返回先出现的那个，
于是留下了不合格的第 1 张 —— 用户看到"勾没填"，根因在这里。
"""

from __future__ import annotations

from app.schemas.task import ArtworkCandidate
from app.services.tools.select_artwork import pick_best_artwork


def _artwork(attempt: int, score: float, passed: bool) -> ArtworkCandidate:
    return ArtworkCandidate(
        attempt=attempt, path=f"artwork_a{attempt}.png", score=score, passed=passed
    )


def test_passed_wins_over_unfinished_even_at_equal_score() -> None:
    """AF1 的真实情形：同分，必须要有通过的那张。"""
    items = [_artwork(1, 0.9525, False), _artwork(2, 0.9525, True)]
    assert pick_best_artwork(items).attempt == 2


def test_passed_wins_even_with_lower_score() -> None:
    """"过没过"与"像不像"是两件事：通过了就优先于没通过的，哪怕分数低一点。"""
    items = [_artwork(1, 0.99, False), _artwork(2, 0.86, True)]
    assert pick_best_artwork(items).attempt == 2


def test_higher_score_wins_among_passed() -> None:
    items = [_artwork(1, 0.86, True), _artwork(2, 0.95, True)]
    assert pick_best_artwork(items).attempt == 2


def test_higher_score_wins_among_failed() -> None:
    """两张都没过（产品原则：不 dead-end，仍要交付最接近的一张）。"""
    items = [_artwork(1, 0.70, False), _artwork(2, 0.78, False)]
    assert pick_best_artwork(items).attempt == 2


def test_later_attempt_wins_on_full_tie() -> None:
    """分数与通过状态都一样时取更晚的一次（后一次通常更收敛）。"""
    items = [_artwork(1, 0.90, True), _artwork(2, 0.90, True)]
    assert pick_best_artwork(items).attempt == 2


def test_empty_returns_none() -> None:
    assert pick_best_artwork([]) is None


def test_missing_fields_do_not_crash() -> None:
    """老任务记录里可能缺 passed / score（schema 允许 None）。"""
    items = [
        ArtworkCandidate(attempt=1, path="a1.png", score=None, passed=None),
        ArtworkCandidate(attempt=2, path="a2.png", score=0.5, passed=None),
    ]
    assert pick_best_artwork(items).attempt == 2
