"use client";

/**
 * 草稿上的「马赛克正在生成」动效（产品经理要求：要有一种"正在生成"的感觉）。
 *
 * 设计（2026-09-23 第二版，第一版整片铺满把画糊住了，已改）：
 * - 用一块低分辨率 canvas（26×17 网格）叠在草稿上，`image-rendering: pixelated` → 天然马赛克块；
 * - 只让**一条从左向右移动的"计算前沿"**在闪：
 *   · 前沿左侧＝已定格：几乎透明，只偶尔极轻地闪一下；
 *   · 前沿附近＝正在算：亮度跳变的马赛克（观感主体）；
 *   · 前沿右侧＝还没算：稀疏的淡浮尘；
 * - 这样既能表达"还在生成"，又不会把草稿盖住（草稿必须看得清鞋型）。
 * - 尊重 `prefers-reduced-motion`：偏好关闭时直接不画（不做纯装饰动画）。
 *
 * 注意：它只是**展示层**。草稿本身还是那张  的 CV 边缘图，正式稿完成时整体淡入替换。
 */
import { useEffect, useRef } from "react";

const COLS = 26;
const ROWS = 17;
const FRAME_MS = 80; // ~12fps：够"闪"，又不烧 CPU
const CYCLE_MS = 12_000; // 前沿走完一轮的时间

export function DraftMosaic({ active }: { active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !active) return;
    if (typeof window === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return; // 无障碍：跳过装饰动画

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const total = COLS * ROWS;
    const level = new Float32Array(total);
    let raf = 0;
    let last = 0;
    let startedAt = 0;

    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (now - last < FRAME_MS) return;
      last = now;
      if (!startedAt) startedAt = now;
      const progress = ((now - startedAt) % CYCLE_MS) / CYCLE_MS;
      const frontier = progress * (COLS + 6) - 3; // 前置 3 列，让前沿从画面外扫进画面外

      ctx.clearRect(0, 0, COLS, ROWS);
      for (let i = 0; i < total; i += 1) {
        const col = i % COLS;
        const distance = col - frontier;

        if (distance < -2) {
          // 已定格：几乎透明，偶尔极轻闪一下（说明还在跑，但不干扰看图）
          level[i] = level[i] * 0.7 + (Math.random() < 0.015 ? 0.06 : 0);
        } else if (distance <= 2) {
          // 正在算：亮度随机跳变（马赛克的"本体"）
          level[i] = Math.random() < 0.5 ? Math.random() * 0.3 + 0.14 : level[i] * 0.55;
        } else {
          // 还没算：稀疏淡浮尘
          level[i] = Math.random() < 0.06 ? Math.random() * 0.1 + 0.03 : level[i] * 0.6;
        }

        if (level[i] <= 0.02) continue;
        ctx.fillStyle = `rgba(92, 100, 124, ${Math.min(0.32, level[i]).toFixed(3)})`;
        ctx.fillRect(col, Math.floor(i / COLS), 1, 1);
      }
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  if (!active) return null;
  return <canvas ref={canvasRef} width={COLS} height={ROWS} className="draft-mosaic" aria-hidden />;
}
