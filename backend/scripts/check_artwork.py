#!/usr/bin/env python
"""画稿自检工具：比例 / 纯二值 / 白底（PRD 硬指标）。

用法：
    python scripts/check_artwork.py <图片路径> [--width 1536] [--height 1024]

退出码：0 = 合格；1 = 不合格（并打印每一项的实际数值）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cv.binarize import check_artwork  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="检查画稿是否符合 3:2 白底纯黑白规范")
    parser.add_argument("image", type=Path, help="画稿文件路径（PNG）")
    parser.add_argument("--width", type=int, default=1536)
    parser.add_argument("--height", type=int, default=1024)
    args = parser.parse_args()

    if not args.image.is_file():
        print(f"[错误] 文件不存在：{args.image}")
        return 1

    check = check_artwork(args.image.read_bytes(), args.width, args.height)
    print(f"文件：{args.image}")
    print(f"尺寸：{check['width']}x{check['height']}（期望 {args.width}x{args.height}）")
    print(f"比例：{check['ratio']} -> {'OK' if check['ratio_ok'] else '不合格'}")
    print(f"纯二值（只有 0/255）：{'OK' if check['binary'] else '不合格'}")
    print(f"白底占比：{check['white_ratio']:.2%} -> {'OK' if check['background_ok'] else '不合格'}")
    print(f"canvas_ratio 得分：{check['canvas_score']}")
    print("提示：'无文字' 由人工目视确认（本项目从不叠加文字，overlay_text=none）")

    ok = check["ratio_ok"] and check["binary"] and check["background_ok"]
    print("\n结论：" + ("合格 ✅" if ok else "不合格 ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
