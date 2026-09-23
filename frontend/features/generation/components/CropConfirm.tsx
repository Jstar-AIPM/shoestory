"use client";

/**
 * 裁切确认：在图上叠加一个可拖拽、可缩放的裁切框（像微信换头像那样）。
 * - 坐标一律是**原图坐标**（x,y,w,h），渲染时按显示比例换算；
 * - 整框可拖 + 四角把手可缩放，把手热区放大到 28px 照顾手指；
 * - 自动建议框由后端 CV 给出，用户不调也能直接用。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import type { CropBox } from "@/lib/api/types";

const MIN_SIZE = 32; // 原图像素的最小框边长（与后端一致）
const HANDLE_SIZE = 28; // 热区（px），视觉上画小一点
const CORNERS = ["tl", "tr", "bl", "br"] as const;
type Corner = (typeof CORNERS)[number];

type DragState =
  | { kind: "move"; startX: number; startY: number; origin: CropBox }
  | { kind: "resize"; corner: Corner; startX: number; startY: number; origin: CropBox };

export function CropConfirm({
  imageUrl,
  imageWidth,
  imageHeight,
  crop,
  onCropChange,
  onConfirm,
  onReset,
  busy,
  guide,
}: {
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  crop: CropBox;
  onCropChange: (box: CropBox) => void;
  onConfirm: () => void;
  onReset: () => void;
  busy: boolean;
  guide?: string;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [display, setDisplay] = useState({ width: 0, height: 0 });

  // 图片按容器宽度等比缩放，这里量出实际显示尺寸用于坐标换算
  useEffect(() => {
    const el = imgRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setDisplay({ width: rect.width, height: rect.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const sx = display.width / Math.max(1, imageWidth);
  const sy = display.height / Math.max(1, imageHeight);

  const clamp = useCallback(
    (box: CropBox): CropBox => {
      const w = Math.max(MIN_SIZE, Math.min(box.w, imageWidth));
      const h = Math.max(MIN_SIZE, Math.min(box.h, imageHeight));
      const x = Math.max(0, Math.min(box.x, imageWidth - w));
      const y = Math.max(0, Math.min(box.y, imageHeight - h));
      return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
    },
    [imageWidth, imageHeight],
  );

  const startDrag = useCallback(
    (e: React.PointerEvent, kind: DragState["kind"], corner?: Corner) => {
      if (busy) return;
      e.preventDefault();
      e.stopPropagation();
      dragRef.current =
        kind === "move"
          ? { kind, startX: e.clientX, startY: e.clientY, origin: crop }
          : { kind, corner: corner as Corner, startX: e.clientX, startY: e.clientY, origin: crop };
    },
    [busy, crop],
  );

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dx = (e.clientX - drag.startX) / Math.max(0.0001, sx);
      const dy = (e.clientY - drag.startY) / Math.max(0.0001, sy);
      const origin = drag.origin;

      if (drag.kind === "move") {
        onCropChange(clamp({ ...origin, x: origin.x + dx, y: origin.y + dy }));
        return;
      }

      let { x, y, w, h } = origin;
      if (drag.corner.includes("r")) w = origin.w + dx;
      if (drag.corner.includes("b")) h = origin.h + dy;
      if (drag.corner.includes("l")) {
        const right = origin.x + origin.w;
        w = origin.w - dx;
        x = right - Math.max(MIN_SIZE, w);
      }
      if (drag.corner.includes("t")) {
        const bottom = origin.y + origin.h;
        h = origin.h - dy;
        y = bottom - Math.max(MIN_SIZE, h);
      }
      onCropChange(clamp({ x, y, w, h }));
    },
    [clamp, onCropChange, sx, sy],
  );

  const stopDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDrag);
    window.addEventListener("pointercancel", stopDrag);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDrag);
      window.removeEventListener("pointercancel", stopDrag);
    };
  }, [onPointerMove, stopDrag]);

  const rect = {
    left: crop.x * sx,
    top: crop.y * sy,
    width: crop.w * sx,
    height: crop.h * sy,
  };

  return (
    <Card className="px-5 py-5 sm:px-6">
      <h2 className="text-[17px] font-semibold text-ink">框出您要画的那一双</h2>
      <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
        拖动方框或四角把手，只包住一双鞋。框得越准，线稿越接近原鞋。
      </p>

      {guide ? (
        <div className="mt-3">
          <Alert tone={guide.includes("好几双") || guide.includes("不止一双") ? "warn" : "info"}>{guide}</Alert>
        </div>
      ) : null}

      <div className="relative mt-4 select-none overflow-hidden rounded-[var(--radius-btn)] bg-black/[0.04]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={imgRef}
          src={imageUrl}
          alt="待裁切的鞋图"
          className="block w-full"
          draggable={false}
        />

        {/* 暗部遮罩（框外区域变暗） */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            boxShadow: `0 0 0 9999px rgba(17, 17, 17, 0.45)`,
            clipPath: `polygon(0 0, 0 100%, ${rect.left}px 100%, ${rect.left}px ${rect.top}px, ${rect.left + rect.width}px ${rect.top}px, ${rect.left + rect.width}px ${rect.top + rect.height}px, ${rect.left}px ${rect.top + rect.height}px, ${rect.left}px 100%, 100% 100%, 100% 0)`,
          }}
        />

        {/* 裁切框 */}
        <div
          className="absolute cursor-move touch-none"
          style={{
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
            outline: "2px solid #ffffff",
            boxShadow: "0 0 0 1px rgba(17,17,17,0.35)",
          }}
          onPointerDown={(e) => startDrag(e, "move")}
          role="group"
          aria-label="裁切框（可拖动）"
        >
          {CORNERS.map((corner) => (
            <span
              key={corner}
              onPointerDown={(e) => startDrag(e, "resize", corner)}
              className="absolute z-10 touch-none"
              style={{
                width: HANDLE_SIZE,
                height: HANDLE_SIZE,
                left: corner.includes("l") ? -HANDLE_SIZE / 2 : undefined,
                right: corner.includes("r") ? -HANDLE_SIZE / 2 : undefined,
                top: corner.includes("t") ? -HANDLE_SIZE / 2 : undefined,
                bottom: corner.includes("b") ? -HANDLE_SIZE / 2 : undefined,
              }}
            >
              <span
                className="absolute left-1/2 top-1/2 block h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-[3px] border-2 border-white bg-[#5865f2] shadow"
                aria-hidden
              />
            </span>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button variant="primary" className="btn-blurple" onClick={onConfirm} disabled={busy}>
          {busy ? "正在识别…" : "确认框选"}
        </Button>
        <Button variant="ghost" onClick={onReset} disabled={busy}>
          换一张
        </Button>
      </div>
      <p className="mt-2.5 text-[12.5px] text-faint">
        确认后会识别这是不是鞋、是什么鞋（本机计算），还不开始画。
      </p>
    </Card>
  );
}
