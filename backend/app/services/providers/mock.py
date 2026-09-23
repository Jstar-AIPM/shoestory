"""Mock 提供方：无 Key 也能跑通完整链路（演示模式 / 第一层测试）。

它不是“假装成功”：所有产出都是本地确定性生成的占位图（纯黑白线稿、示例鞋图），
轨迹里 provider=mock、model=mock-*，界面上也会显示“演示模式（mock）”。
"""

from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.config import Settings
from app.schemas.enums import SOURCE_CREDIT
from app.schemas.inspect import PhotoInspectOut  # noqa: F401
from app.schemas.llm import (
    ModelCandidate,
    ModelResolveOut,
    QualityReportOut,
    SourceScreenItem,
    SourceScreenOut,
)
from app.schemas.task import SourceCandidate
from app.services.providers.base import CallRecorder, timer
from app.services.style.loader import StyleTemplate

MOCK_BRAND = "Demo"
MOCK_CANDIDATES = [
    ModelCandidate(name="Nike KD 12", reason="同系列相近型号"),
    ModelCandidate(name="Nike KD 13", reason="同系列相近型号"),
    ModelCandidate(name="Nike KD 14", reason="同系列相近型号"),
]
_COLOR_WORDS = ("白红", "黑白", "薄荷绿", "灰黑", "黑红", "纯白", "配色")
_MOCK_SOURCE_DIR = Path(tempfile.gettempdir()) / "lvli_mock_sources"


# --------------------------------------------------------------------------- 型号校对
class MockModelResolver:
    name = "mock"
    model = "mock-resolver"
    mode = "mock"

    def resolve(self, raw_query: str, known_brands: list[str], recorder: CallRecorder) -> ModelResolveOut:
        recorder.check("text")
        with timer() as box:
            numeric = [int(n) for n in re.findall(r"\d+", raw_query)]
            number = numeric[0] if numeric else None
            cleaned = raw_query.lower()
            for word in _COLOR_WORDS:
                cleaned = cleaned.replace(word, "")
            letters = "".join(re.findall(r"[a-z]+", cleaned))

            if number is not None and number >= 99:
                result = ModelResolveOut(
                    normalized="",
                    brand="",
                    confidence=0.2,
                    exists=False,
                    candidates=MOCK_CANDIDATES,
                    note="（mock）型号看起来不存在，已给出相近候选",
                )
            elif not letters and number is None:
                result = ModelResolveOut(
                    normalized="",
                    brand="",
                    confidence=0.2,
                    exists=False,
                    candidates=MOCK_CANDIDATES,
                    note="（mock）无法识别型号",
                )
            else:
                brand, name = self._guess(letters, number, raw_query, known_brands)
                result = ModelResolveOut(
                    normalized=name,
                    brand=brand,
                    confidence=0.9,
                    exists=True,
                    candidates=[],
                    note="（mock）补全品牌并规范化大小写",
                )
        recorder.record("text", provider=self.name, model=self.model, duration_ms=box["ms"])
        return result

    @staticmethod
    def _guess(
        letters: str, number: int | None, raw_query: str, known_brands: list[str]
    ) -> tuple[str, str]:
        num = str(number) if number is not None else ""
        cleaned = raw_query.lower()
        brand = next((b for b in known_brands or [] if b.lower() in cleaned), None)
        rest = cleaned if brand is None else cleaned.replace(brand.lower(), " ")
        rest_letters = "".join(re.findall(r"[a-z]+", rest))

        series = f"{rest_letters.upper()} {num}".strip() or letters.upper()
        if "jordan" in letters or letters.startswith("aj"):
            return "Air Jordan", f"Air Jordan {num}".strip()
        if "kd" in rest_letters or "kd" in letters:
            return "Nike", f"Nike KD {num}".strip()
        if "pg" in rest_letters or "pg" in letters:
            return "Nike", f"Nike PG {num}".strip()
        if "kyrie" in letters:
            return "Nike", f"Nike Kyrie {num}".strip()
        if "lebron" in letters:
            return "Nike", f"Nike LeBron {num}".strip()
        if "dunk" in letters:
            return "Nike", "Nike Dunk Low"
        if "yeezy" in letters:
            return "adidas", f"adidas Yeezy {num}".strip()
        if "airforce" in letters or "af1" in letters:
            return "Nike", "Nike Air Force 1"
        if brand:
            return brand, f"{brand} {series}".strip()
        return MOCK_BRAND, series


# --------------------------------------------------------------------------- 质检
class MockQualityJudge:
    name = "mock"
    model = "mock-judge"
    mode = "mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def inspect_photo(self, *, image: bytes, recorder) -> "PhotoInspectOut":
        """mock 体检：默认判为"是鞋 + ASICS 交叉条纹 + 有条文字"，确定性便于测试。"""
        from app.schemas.inspect import LogoInfo, PhotoInspectOut, ShoeText

        recorder.check("vision")
        with timer():
            pass
        return PhotoInspectOut(
            is_shoe=True,
            confidence=0.95,
            shoe_count=1,
            subject_description="",
            brand="ASICS",
            model_name="GEL-Nimbus 27",
            colorway="白蓝",
            logo=LogoInfo(type="两侧交叉条纹", position="鞋身两侧", fill_required=True, confidence=0.9),
            texts=[ShoeText(text="GEL", position="鞋侧中足", box=(0.60, 0.66, 0.24, 0.10))],
            notes="mock",
        )

    def screen_sources(self, *, images: list[bytes], model_name: str, recorder) -> SourceScreenOut:
        """mock 预筛：第 1 张判为可用，其余判为不可用（确定性，便于测试）。"""
        recorder.check("vision")
        with timer() as box:
            results = []
            for index in range(len(images)):
                usable = index == 0
                results.append(
                    SourceScreenItem(
                        index=index,
                        single_shoe=usable,
                        side_view=usable,
                        clean_background=usable,
                        sharp=True,
                        score=0.9 if usable else 0.2,
                        reason="（mock）第 1 张视为单只正侧面" if usable else "（mock）视为多只鞋/角度不佳",
                    )
                )
            out = SourceScreenOut(results=results, best_index=0 if images else -1)
        recorder.record("vision", provider=self.name, model=self.model, duration_ms=box["ms"],
                        detail={"task": "screen_sources", "candidates": len(images)})
        return out

    def judge(
        self,
        *,
        model_name: str,
        style: StyleTemplate,
        source_png: bytes | None,
        artwork_png: bytes,
        recorder: CallRecorder,
    ) -> QualityReportOut:
        recorder.check("vision")
        low = self.settings.mock_quality == "low"
        with timer() as box:
            if low:
                report = QualityReportOut(
                    shoe_silhouette_match=0.40,
                    logo_legibility=0.30,
                    style_consistency=0.50,
                    noise_level=0.40,
                    issues=["（mock）鞋型与原鞋偏差大", "（mock）Logo 形状不清晰"],
                    verdict="fail",
                    reason="（mock）故意产出低分，用于验证自动重试与失败交裁决",
                )
            else:
                report = QualityReportOut(
                    shoe_silhouette_match=0.90,
                    logo_legibility=0.85,
                    style_consistency=0.90,
                    noise_level=0.88,
                    issues=[],
                    verdict="pass",
                    reason="（mock）轮廓、Logo 与线条分层均符合风格模板",
                )
        recorder.record(
            "vision",
            provider=self.name,
            model=self.model,
            duration_ms=box["ms"],
            detail={"mock_low": low},
        )
        return report


# --------------------------------------------------------------------------- 线稿生成
def _draw_mock_lineart(width: int, height: int, attempt: int) -> bytes:
    """演示模式占位线稿（纯黑白、无文字）。

    刻意按**参考图实测的风格区间**来画（粗轮廓 + 实心黑块 + 成排虚线 + 稀疏圆点，
    零排线），这样演示模式的观感与真实产出同源；参数由 scripts/style_calibrate.py
    的量化区间标定，见 tests/unit/test_structure_reference.py 的断言。
    """
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    weight = 16 + min(attempt - 1, 2)  # 重试时线条略变粗，肉眼可分辨不同候选

    left, right = int(width * 0.07), int(width * 0.93)
    top, bottom = int(height * 0.30), int(height * 0.80)
    toe = (left, bottom - int(height * 0.10))

    outline = [
        toe,
        (left + 150, bottom - 170),
        (left + 380, top + 40),
        (right - 260, top + 20),
        (right - 30, top + 90),
        (right, bottom - 150),
        (right - 120, bottom - 60),
        (left + 40, bottom - 30),
        toe,
    ]
    draw.line(outline, fill=(0, 0, 0), width=weight, joint="curve")

    # 实心黑中底：参考风格靠"黑块"而不是排线表达明暗
    mid_h = int(height * 0.06)
    draw.polygon(
        [
            (left + 20, bottom - mid_h),
            (right - 40, bottom - mid_h - 30),
            (right - 50, bottom - 10),
            (left + 40, bottom - int(mid_h * 0.35)),
        ],
        fill=(0, 0, 0),
    )
    # 实心黑 Logo 占位块（不画任何文字）
    draw.polygon(
        [
            (left + 380, top + 150),
            (left + 515, top + 210),
            (left + 490, top + 250),
            (left + 350, top + 200),
        ],
        fill=(0, 0, 0),
    )
    # 车缝线：成排虚线
    for row in range(2):
        y = top + 120 + row * 46
        for step in range(9):
            x = left + 300 + step * 60
            draw.line([(x, y), (x + 34, y)], fill=(0, 0, 0), width=max(2, weight // 4))
    # 透气孔：规律稀疏小圆点
    for index in range(80):
        column, row = index % 10, index // 10
        x = left + 260 + column * 34
        y = top + 200 + row * 34
        draw.ellipse([x, y, x + 7, y + 7], fill=(0, 0, 0))

    gray = img.convert("L").point(lambda value: 0 if value < 128 else 255)
    buffer = io.BytesIO()
    gray.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


class MockLineartGenerator:
    name = "mock"
    model = "mock-lineart"
    mode = "mock"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(
        self,
        *,
        canvas_png: bytes | None,
        style: StyleTemplate,
        attempt: int,
        recorder: CallRecorder,
        structure_reference: bytes | None = None,  # mock 忽略结构骨架/型号，但接口保持一致
        model_name: str | None = None,
        logo_fill: str | None = None,  # mock 忽略 Logo/文字提示，但接口保持一致
        shoe_texts: list[str] | None = None,
    ) -> bytes:
        recorder.check("image")
        with timer() as box:
            width = int(style.provider_params.get("size", f"{self.settings.artwork_width}x{self.settings.artwork_height}").split("x")[0])
            height = int(style.provider_params.get("size", f"{self.settings.artwork_width}x{self.settings.artwork_height}").split("x")[1])
            data = _draw_mock_lineart(width, height, attempt)
        recorder.record(
            "image",
            provider=self.name,
            model=self.model,
            duration_ms=box["ms"],
            detail={"attempt": attempt, "size": f"{width}x{height}"},
        )
        return data


# --------------------------------------------------------------------------- 搜图
def _draw_mock_photo(width: int, height: int, variant: int) -> bytes:
    """画一张“示例鞋图”（浅灰背景 + 彩色鞋身），用于走通取图链路。"""
    palette = [(38, 38, 38), (200, 60, 60), (40, 90, 170)][variant % 3]
    img = Image.new("RGB", (width, height), (232, 232, 232))
    draw = ImageDraw.Draw(img)
    left, right = int(width * 0.12), int(width * 0.88)
    bottom = int(height * 0.80)
    top = int(height * 0.34)
    draw.polygon(
        [
            (left, bottom),
            (left + 60, bottom - 110),
            (left + 260, top),
            (right - 150, top + 20),
            (right - 20, bottom - 140),
            (right, bottom),
        ],
        fill=palette,
        outline=(20, 20, 20),
    )
    draw.polygon(
        [(left + 10, bottom), (right, bottom), (right - 20, bottom - 40), (left + 30, bottom - 40)],
        fill=(245, 245, 245),
        outline=(20, 20, 20),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


class MockShoeImageSearch:
    name = "mock"
    mode = "mock"

    def search(
        self, *, model_name: str, limit: int, recorder: CallRecorder
    ) -> list[SourceCandidate]:
        recorder.check("search")
        with timer() as box:
            _MOCK_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
            candidates: list[SourceCandidate] = []
            sizes = [(1200, 800), (1000, 900), (900, 700)]
            for index in range(min(3, limit)):
                width, height = sizes[index % len(sizes)]
                path = _MOCK_SOURCE_DIR / f"mock_{index}_{width}x{height}.png"
                if not path.exists():
                    path.write_bytes(_draw_mock_photo(width, height, index))
                candidates.append(
                    SourceCandidate(
                        index=index,
                        provider=self.name,
                        local_path=str(path),
                        width=width,
                        height=height,
                        credit=f"{SOURCE_CREDIT}（演示模式占位图，非真实检索结果）",
                    )
                )
        recorder.record(
            "search",
            provider=self.name,
            model="mock-search",
            duration_ms=box["ms"],
            detail={"found": len(candidates)},
        )
        return candidates
